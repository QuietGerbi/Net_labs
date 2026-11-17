import random
import unittest

from snakes_game import codec, rules
from snakes_game.messages import envelope
from snakes_game.model import Config, Player, Snake, World
from snakes_game.proto import snakes_pb2 as pb


def world(w=10, h=10, food=0):
    return World("g", Config(w, h, food, 1000), 0, [], [], [], 10)


def add(w, pid, cells, d, status=pb.PLAYING):
    w.players.append(Player(pid, f"p{pid}", pb.NORMAL, status))
    w.snakes.append(Snake(pid, cells, d))
    return w.snakes[-1]


class CodecTests(unittest.TestCase):
    def test_snake_roundtrip_with_wrap(self):
        cells = [(1, 0), (0, 0), (9, 0), (9, 1), (9, 2), (8, 2)]
        s = Snake(1, cells, pb.RIGHT)
        p = codec.encode_snake(s, 10, 10)
        self.assertEqual(codec.decode_snake(p, 10, 10).cells, cells)
        # смещения осевые и ненулевые, нулевая компонента не записана
        for off in p.points[1:]:
            self.assertEqual((off.x != 0) + (off.y != 0), 1)

    def test_long_straight_snake_crossing_border(self):
        cells = [((5 - i) % 20, 3) for i in range(12)]
        p = codec.encode_snake(Snake(1, cells, pb.RIGHT), 20, 10)
        self.assertEqual(len(p.points), 2)  # голова + один отрезок
        self.assertEqual(p.points[1].x, -11)
        self.assertEqual(codec.decode_snake(p, 20, 10).cells, cells)

    def test_decode_rejects_garbage(self):
        p = pb.GameState.Snake(player_id=1, head_direction=pb.UP)
        p.points.add()
        p.points.add()  # нулевое смещение
        with self.assertRaises(ValueError):
            codec.decode_snake(p, 10, 10)

    def test_max_state_size(self):
        cfg = Config(100, 100, 10, 100)
        w = World("g" * 32, cfg, 2 ** 31 - 2, next_player_id=2 ** 31 - 2)
        for i in range(6):
            p = Player(2 ** 31 - 10 + i, "я" * 12, pb.NORMAL if i else pb.MASTER, pb.PLAYING if i < 4 else pb.VIEWING,
                       2 ** 31 - 1, pb.ROBOT, "255.255.255.255", 65535)
            w.players.append(p)
        for i in range(4):  # 32 клетки, поворот на каждом шаге (лесенка)
            x, y, cells = 90 + i, 50 + i * 10, []
            for k in range(32):
                cells.append((x, y))
                if k % 2 == 0:
                    x -= 1
                else:
                    y -= 1
            w.snakes.append(Snake(w.players[i].id, cells, pb.LEFT))
        w.foods = [(99 - i, 99) for i in range(14)]
        m = envelope("g" * 32, 2 ** 31 - 10, 2 ** 31 - 9)
        m.msg_seq = 2 ** 62
        m.state.state.CopyFrom(codec.world_to_state(w, w.players[0].id))
        size = len(m.SerializeToString())
        self.assertLessEqual(size, 1145)

    def test_world_roundtrip(self):
        w = world()
        w.players.append(Player(1, "m", pb.MASTER, pb.PLAYING, 3))
        w.players.append(Player(2, "n", pb.NORMAL, pb.PLAYING, 0, ip="1.2.3.4", port=99))
        w.snakes.append(Snake(1, [(2, 2), (2, 3)], pb.UP))
        w.snakes.append(Snake(2, [(7, 7), (6, 7)], pb.RIGHT))
        w.foods = [(0, 0), (5, 6)]
        st = codec.world_to_state(w, 1)
        w2 = codec.world_from_proto(st, w.config, "g", ("9.9.9.9", 1))
        self.assertEqual(w2.foods, w.foods)
        self.assertEqual([s.cells for s in w2.snakes], [s.cells for s in w.snakes])
        self.assertEqual(w2.master().endpoint, ("9.9.9.9", 1))


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(3)

    def test_spawn_has_two_cells_no_food_and_5x5_free(self):
        w = world()
        add(w, 1, [(5, 5), (5, 6)], pb.UP)
        w.foods = [(0, 0)]
        for _ in range(20):
            s = rules.find_spawn(w, self.rng)
            self.assertIsNotNone(s)
            self.assertEqual(len(s.cells), 2)
            hx, hy = s.cells[0]
            self.assertNotIn(s.cells[0], w.foods)
            self.assertNotIn(s.cells[1], w.foods)
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    self.assertNotIn(((hx + dx) % 10, (hy + dy) % 10), [(5, 5), (5, 6)])

    def test_spawn_limits(self):
        w = world()
        for i in range(4):
            add(w, i + 1, [(i * 3, 0), (i * 3, 1)], pb.UP)
        self.assertIsNone(rules.find_spawn(w, self.rng))

    def test_food_replenish_target(self):
        w = world(food=3)
        add(w, 1, [(5, 5), (5, 6)], pb.UP)
        rules.replenish_food(w, self.rng)
        self.assertEqual(len(w.foods), 4)
        rules.replenish_food(w, self.rng)
        self.assertEqual(len(w.foods), 4)
        self.assertTrue(set(w.foods).isdisjoint(rules.occupied_cells(w)))

    def test_move_wraps_and_tail_freed(self):
        w = world()
        add(w, 1, [(0, 0), (1, 0)], pb.LEFT)
        rules.step(w, {})
        self.assertEqual(w.snakes[0].cells, [(9, 0), (0, 0)])

    def test_eat_grows_and_scores(self):
        w = world()
        add(w, 1, [(2, 2), (2, 3)], pb.UP)
        w.foods = [(2, 1)]
        rules.step(w, {})
        self.assertEqual(len(w.snakes[0].cells), 3)
        self.assertEqual(w.players[0].score, 1)
        self.assertEqual(w.foods, [])

    def test_len32_eats_without_growing(self):
        w = world(20, 20)
        cells = [(i, 0) for i in range(31, -1, -1)]
        add(w, 1, cells[:], pb.RIGHT)
        w.foods = [(0, 1)]
        w.snakes[0].cells = [(5, 5)] + [(5, 5 + i) for i in range(1, 32)]
        w.snakes[0].direction = pb.UP
        w.foods = [(5, 4)]
        rules.step(w, {})
        self.assertEqual(len(w.snakes[0].cells), 32)
        self.assertEqual(w.players[0].score, 1)

    def test_reverse_is_ignored(self):
        w = world()
        add(w, 1, [(2, 2), (2, 3)], pb.UP)
        rules.step(w, {1: pb.DOWN})
        self.assertEqual(w.snakes[0].head, (2, 1))

    def test_self_collision_no_points(self):
        w = world()
        add(w, 1, [(2, 2), (3, 2), (3, 3), (2, 3), (1, 3), (1, 2)], pb.LEFT)
        # голова идёт вниз в (2,3) — тело
        dead = rules.step(w, {1: pb.DOWN})
        self.assertEqual(dead, [1])
        self.assertEqual(w.players[0].score, 0)
        self.assertEqual(w.players[0].status, pb.VIEWING)
        self.assertEqual(w.snakes, [])

    def test_chase_freed_tail_is_safe_but_not_when_eating(self):
        w = world()
        add(w, 1, [(5, 5), (5, 6), (5, 7)], pb.UP)       # преследуемая
        add(w, 2, [(4, 7), (3, 7)], pb.RIGHT)            # голова входит в хвост (5,7)
        rules.step(w, {})
        self.assertEqual(len(w.snakes), 2)
        w = world()
        add(w, 1, [(5, 5), (5, 6), (5, 7)], pb.UP)
        add(w, 2, [(4, 7), (3, 7)], pb.RIGHT)
        w.foods = [(5, 4)]                               # преследуемая ест => хвост остаётся
        dead = rules.step(w, {})
        self.assertEqual(dead, [2])
        self.assertEqual(w.players[0].score, 2)          # еда + врезавшаяся голова

    def test_head_on_both_die_each_scores(self):
        w = world()
        add(w, 1, [(4, 5), (3, 5)], pb.RIGHT)
        add(w, 2, [(6, 5), (7, 5)], pb.LEFT)
        dead = rules.step(w, {})
        self.assertEqual(sorted(dead), [1, 2])
        self.assertEqual([p.score for p in w.players], [1, 1])

    def test_swap_heads_kills_both(self):
        w = world()
        add(w, 1, [(4, 5), (3, 5)], pb.RIGHT)
        add(w, 2, [(5, 5), (6, 5)], pb.LEFT)
        dead = rules.step(w, {})
        self.assertEqual(sorted(dead), [1, 2])

    def test_three_heads_one_cell(self):
        w = world()
        add(w, 1, [(4, 5), (3, 5)], pb.RIGHT)
        add(w, 2, [(6, 5), (7, 5)], pb.LEFT)
        add(w, 3, [(5, 4), (5, 3)], pb.DOWN)
        w.foods = [(5, 5)]
        dead = rules.step(w, {})
        self.assertEqual(sorted(dead), [1, 2, 3])
        self.assertEqual([p.score for p in w.players], [3, 3, 3])  # N-1 + еда

    def test_score_saturates(self):
        w = world()
        add(w, 1, [(2, 2), (2, 3)], pb.UP)
        w.players[0].score = 2 ** 31 - 1
        w.foods = [(2, 1)]
        rules.step(w, {})
        self.assertEqual(w.players[0].score, 2 ** 31 - 1)


if __name__ == "__main__":
    unittest.main()
