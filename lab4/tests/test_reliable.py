import unittest

from snakes_game import constants as C
from snakes_game.messages import ProtocolError, envelope, parse_message
from snakes_game.proto import snakes_pb2 as pb
from snakes_game.reliable import DedupTable, Outbox
from tests.fakes import FakeClock


class Sock:
    def __init__(self):
        self.sent = []

    def sendto(self, data, ep):
        self.sent.append((data, ep))


def ping(game="g"):
    m = envelope(game, 1, 2)
    m.ping.SetInParent()
    return m


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.sock = FakeClock(), Sock()
        self.out = Outbox(self.sock, self.clock)
        self.ep = ("1.1.1.1", 1)

    def test_retransmit_every_100ms_same_seq_until_ack(self):
        seq = self.out.send(self.ep, ping(), key=None)
        self.clock.t += 0.05
        self.out.retransmit()
        self.assertEqual(len(self.sock.sent), 1)
        self.clock.t += 0.06
        self.out.retransmit()
        self.assertEqual(len(self.sock.sent), 2)
        self.assertEqual(parse_message(self.sock.sent[1][0]).msg_seq, seq)
        self.assertIsNotNone(self.out.take(self.ep, seq))
        self.clock.t += 1
        self.out.retransmit()
        self.assertEqual(len(self.sock.sent), 2)

    def test_ack_from_wrong_endpoint_is_unmatched(self):
        seq = self.out.send(self.ep, ping())
        self.assertIsNone(self.out.take(("2.2.2.2", 2), seq))
        self.assertIn(seq, self.out.pending)

    def test_replaceable_messages_are_superseded(self):
        for _ in range(5):
            self.out.send(self.ep, ping(), key="state")
        self.assertEqual(len(self.out.pending), 1)

    def test_control_ops_survive_queue_limit(self):
        for _ in range(100):
            self.out.send(self.ep, ping(), key=None)
        self.assertEqual(len(self.out.pending), 100)

    def test_old_request_stops_retransmitting_after_1024_newer(self):
        first = self.out.send(self.ep, ping())
        for _ in range(C.DEDUP_WINDOW):
            self.out.send(self.ep, ping(), key="state")
        self.assertNotIn(first, self.out.pending)

    def test_retarget_keeps_seq_changes_receiver(self):
        seq = self.out.send(self.ep, ping())
        new = ("3.3.3.3", 3)
        self.out.retarget(self.ep, new, 9)
        self.out.retransmit()
        data, ep = self.sock.sent[-1]
        m = parse_message(data)
        self.assertEqual((ep, m.msg_seq, m.receiver_id), (new, seq, 9))

    def test_oversize_message_is_protocol_error(self):
        m = envelope("g")
        m.error.error_message = "x" * 1300
        m.error.request_seq = 1
        with self.assertRaises(ProtocolError):
            self.out.send(self.ep, m)

    def test_ack_does_not_consume_counter(self):
        req = ping()
        req.msg_seq = 77
        self.out.send_ack(self.ep, req, "g", 1, 2)
        self.assertEqual(self.out.next_seq(), 0)
        ack = parse_message(self.sock.sent[0][0])
        self.assertEqual(ack.msg_seq, 77)
        self.assertEqual(ack.WhichOneof("Type"), "ack")


class DedupTests(unittest.TestCase):
    ep = ("1.1.1.1", 1)

    def test_duplicate_returns_cached_response(self):
        d = DedupTable()
        self.assertEqual(d.check(self.ep, 5)[0], "new")
        d.record(self.ep, 5, [b"ack5"])
        self.assertEqual(d.check(self.ep, 5), ("dup", [b"ack5"]))

    def test_below_window_ignored(self):
        d = DedupTable()
        d.record(self.ep, 2000, [b"x"])
        self.assertEqual(d.check(self.ep, 2000 - 1024)[0], "old")
        self.assertEqual(d.check(self.ep, 2000 - 1023)[0], "new")

    def test_gaps_allowed_and_memory_bounded(self):
        d = DedupTable()
        for s in range(0, 10000, 3):
            d.record(self.ep, s, [b"x"])
        self.assertLessEqual(len(d.windows[self.ep].responses), C.DEDUP_WINDOW)

    def test_endpoint_budget(self):
        d = DedupTable(max_endpoints=2)
        d.record(("a", 1), 1, [])
        d.record(("b", 1), 1, [])
        self.assertFalse(d.can_admit(("c", 1)))
        self.assertTrue(d.can_admit(("a", 1)))
        d.record(("c", 1), 1, [])
        self.assertEqual(len(d.windows), 2)


if __name__ == "__main__":
    unittest.main()
