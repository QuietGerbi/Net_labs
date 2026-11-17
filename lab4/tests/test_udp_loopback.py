"""Сквозной тест на настоящих UDP-сокетах (127.0.0.1): два Node в одном процессе."""
import time
import unittest

from snakes_game.model import Config
from snakes_game.node import Node
from snakes_game.proto import snakes_pb2 as pb
from snakes_game.runner import NetworkRunner


def wait_for(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class LoopbackTest(unittest.TestCase):
    def test_create_discover_join_play_leave(self):
        a, b = Node(use_server=False), Node(use_server=False)
        ra, rb = NetworkRunner(a), NetworkRunner(b)
        ra.start()
        rb.start()
        try:
            ra.send("create_local", "game1", "Alice", Config(15, 15, 1, 100), False)
            self.assertTrue(wait_for(lambda: a.session is not None and a.session.is_master))
            port = a.session.sock.port
            # Подменяем multicast: передаём анонс напрямую (в песочнице multicast может быть недоступен).
            data = a.session._announcement_message().SerializeToString()
            b._on_lobby_datagram(data, ("127.0.0.1", port), b.clock(), True)
            self.assertTrue(wait_for(lambda: len(b._games(b.clock())) == 1))
            g = b._games(b.clock())[0]
            self.assertEqual((g.name, g.width, g.state_delay_ms), ("game1", 15, 100))
            rb.send("join", g.name, g.endpoint, pb.PLAYING, "Bob")
            self.assertTrue(wait_for(lambda: rb.view.phase == "game" and rb.view.world is not None))
            self.assertTrue(wait_for(lambda: len(ra.view.world.players) == 2))
            w = rb.view.world
            self.assertEqual({p.name for p in w.players}, {"Alice", "Bob"})
            before = rb.view.world.state_order
            self.assertTrue(wait_for(lambda: rb.view.world.state_order > before + 3))  # игра идёт
            rb.send("status", False)
            self.assertTrue(wait_for(lambda: next(p for p in rb.view.world.players if p.name == "Bob").status == pb.VIEWING))
            rb.send("leave")
            self.assertTrue(wait_for(lambda: rb.view.phase == "lobby" and rb.view.error is None))
            self.assertTrue(wait_for(lambda: len(ra.view.world.players) == 1))
        finally:
            ra.send("quit")
            rb.send("quit")
            ra.join()
            rb.join()


if __name__ == "__main__":
    unittest.main()
