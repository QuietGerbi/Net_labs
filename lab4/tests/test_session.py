import unittest

from snakes_game import constants as C
from snakes_game.model import Config
from snakes_game.proto import snakes_pb2 as pb
from snakes_game.session import Phase
from tests.fakes import FakeNet

CFG = Config(20, 20, 2, 200)


def setup(n_clients=1, **netkw):
    net = FakeNet(**netkw)
    m = net.session("g", "master")
    m.start_as_master(CFG)
    clients = []
    for i in range(n_clients):
        c = net.session("g", f"c{i}")
        c.start_as_client(m.sock.addr, pb.PLAYING, CFG)
        clients.append(c)
    return net, m, clients


class SessionTests(unittest.TestCase):
    def test_join_gets_id_state_and_deputy(self):
        net, m, (c1, c2) = setup(2)
        net.run(1.0)
        self.assertEqual(c1.phase, Phase.ACTIVE)
        self.assertEqual(c2.phase, Phase.ACTIVE)
        self.assertEqual({c1.my_id, c2.my_id}, {2, 3})
        roles = sorted(p.role for p in m.world.players)
        self.assertEqual(roles, [pb.NORMAL, pb.MASTER, pb.DEPUTY])
        self.assertEqual(len(m.world.snakes), 3)
        self.assertEqual(len(m.world.foods), 2 + 3)
        # клиент видит ту же игру
        self.assertEqual(c1.world.state_order >= 1, True)
        self.assertEqual(len(c1.world.players), 3)

    def test_works_under_loss_and_duplication(self):
        net, m, cs = setup(3, loss=0.3, dup=0.3, seed=7)
        net.run(6.0)
        self.assertTrue(all(c.phase == Phase.ACTIVE for c in cs), [c.phase for c in cs])
        self.assertEqual(len(m.world.players), 4)
        self.assertEqual(len({p.id for p in m.world.players}), 4)  # дубли Join не создали лишних игроков
        self.assertEqual(len(m.world.snakes), 4)

    def test_join_refused_when_full(self):
        net, m, cs = setup(3)            # master + 3 = 4 змейки
        net.run(1.0)
        extra = net.session("g", "late")
        extra.start_as_client(m.sock.addr, pb.PLAYING, CFG)
        net.run(1.0)
        self.assertTrue(extra.closed)    # пятую змейку создать нельзя
        self.assertIn("места", extra.error)
        for i in range(2):               # наблюдатели принимаются до лимита в 6 участников
            v = net.session("g", f"v{i}")
            v.start_as_client(m.sock.addr, pb.VIEWING, CFG)
            net.run(1.0)
            self.assertEqual(v.phase, Phase.ACTIVE)
        self.assertEqual(len(m.world.players), 6)
        over = net.session("g", "seventh")
        over.start_as_client(m.sock.addr, pb.VIEWING, CFG)
        net.run(1.0)
        self.assertTrue(over.closed)

    def test_steer_applied_once_per_step(self):
        net, m, (c,) = setup(1)
        net.run(0.5)
        snake = m.world.snake_of(c.my_id)
        d = snake.direction
        new = pb.LEFT if d in (pb.UP, pb.DOWN) else pb.UP
        c.steer(new)
        net.run(0.25)
        self.assertEqual(m.world.snake_of(c.my_id).direction, new)

    def test_viewing_and_return(self):
        net, m, (c,) = setup(1)
        net.run(0.5)
        c.request_status(False)
        net.run(0.5)
        self.assertEqual(c.my_player().status, pb.VIEWING)
        self.assertIsNone(c.world.snake_of(c.my_id))
        c.request_status(True)
        net.run(0.5)
        self.assertEqual(c.my_player().status, pb.PLAYING)
        self.assertIsNotNone(c.world.snake_of(c.my_id))

    def test_leave_removes_player(self):
        net, m, (c1, c2) = setup(2)
        net.run(0.5)
        c1.leave()
        net.run(0.5)
        self.assertTrue(c1.closed and c1.error is None)
        self.assertEqual(len(m.world.players), 2)
        self.assertIsNotNone(m.world.deputy())  # DEPUTY восстановлен

    def test_silent_client_removed_by_timeout(self):
        net, m, (c1, c2) = setup(2)
        net.run(0.5)
        net.kill(c1)
        net.run(1.5)
        self.assertEqual(len(m.world.players), 2)
        self.assertIsNone(m.world.player(c1.my_id))

    def test_failover_to_deputy(self):
        net, m, (c1, c2) = setup(2)
        net.run(1.0)
        deputy = c1 if c1.my_player().role == pb.DEPUTY else c2
        other = c2 if deputy is c1 else c1
        order_before = deputy.world.state_order
        net.kill(m)
        net.run(3.0)
        self.assertTrue(deputy.is_master)
        self.assertEqual(deputy.phase, Phase.ACTIVE)
        self.assertEqual(other.master_ep, deputy.sock.addr)
        self.assertEqual(other.phase, Phase.ACTIVE)
        self.assertEqual(len(deputy.world.players), 2)       # прежний MASTER удалён
        self.assertEqual(other.my_player().role, pb.DEPUTY)  # назначен новый заместитель
        self.assertGreater(other.world.state_order, order_before)
        self.assertEqual(other.world.master().id, deputy.my_id)

    def test_failover_keeps_pending_request(self):
        net, m, (c1, c2) = setup(2)
        net.run(1.0)
        deputy = c1 if c1.my_player().role == pb.DEPUTY else c2
        other = c2 if deputy is c1 else c1
        net.kill(m)
        other.request_status(False)  # запрос уходит «в никуда» и переносится новому MASTER
        net.run(3.0)
        self.assertEqual(other.my_player().status, pb.VIEWING)

    def test_graceful_master_leave_hands_over(self):
        net, m, (c1, c2) = setup(2)
        net.run(1.0)
        deputy = c1 if c1.my_player().role == pb.DEPUTY else c2
        other = c2 if deputy is c1 else c1
        m.leave()
        net.run(2.0)
        self.assertTrue(m.closed and m.error is None)
        self.assertTrue(deputy.is_master)
        self.assertEqual(len(deputy.world.players), 2)
        self.assertEqual(other.master_ep, deputy.sock.addr)

    def test_single_client_becomes_deputy(self):
        net, m, (c,) = setup(1)
        net.run(0.3)
        self.assertEqual(c.my_player().role, pb.DEPUTY)

    def test_normal_without_deputy_fails(self):
        net, m, (c1, c2) = setup(2)
        net.run(1.0)
        normal = c1 if c1.my_player().role == pb.NORMAL else c2
        deputy = c2 if normal is c1 else c1
        net.kill(m)
        net.kill(deputy)
        net.run(4.0)
        self.assertTrue(normal.closed)
        self.assertTrue(normal.error)

    def test_join_to_dead_master_times_out(self):
        net = FakeNet()
        c = net.session("g", "c")
        c.start_as_client(("10.9.9.9", 1), pb.PLAYING, CFG)
        net.run(6.0)
        self.assertTrue(c.closed and c.error)

    def test_stale_and_foreign_packets_ignored(self):
        net, m, (c,) = setup(1)
        net.run(0.5)
        order = c.world.state_order
        # State с другим game_name не применяется
        from snakes_game import codec
        from snakes_game.messages import envelope
        e = envelope("other", m.my_id, c.my_id)
        e.msg_seq = 10 ** 6
        e.state.state.CopyFrom(codec.world_to_state(m.world, m.my_id))
        e.state.state.state_order = order + 50
        c.on_datagram(e.SerializeToString(), m.sock.addr)
        self.assertEqual(c.world.state_order, order)
        # От постороннего endpoint — тоже
        e.game_name = "g"
        c.on_datagram(e.SerializeToString(), ("6.6.6.6", 1))
        self.assertEqual(c.world.state_order, order)

    def test_message_size_never_exceeds_limit(self):
        net, m, cs = setup(4)
        sizes = []
        orig = m.sock.sendto
        m.sock.sendto = lambda d, ep: (sizes.append(len(d)), orig(d, ep))[1]
        net.run(3.0)
        self.assertTrue(sizes and max(sizes) <= C.MAX_DATAGRAM_SIZE)


if __name__ == "__main__":
    unittest.main()
