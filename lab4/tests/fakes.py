"""Виртуальная сеть и часы для детерминированных тестов сессий."""
import random
from collections import deque

from snakes_game.session import Session, SessionContext


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeSock:
    def __init__(self, net, addr):
        self.net, self.addr = net, addr
        self.multicasts = []

    def sendto(self, data, ep):
        self.net.queue.append((data, self.addr, ep))
        return True

    def send_multicast(self, data, ifaces):
        self.multicasts.append(data)
        return 1

    def close(self):
        pass


class FakeNet:
    def __init__(self, loss=0.0, dup=0.0, seed=1):
        self.clock = FakeClock()
        self.queue = deque()
        self.nodes = {}
        self.dead = set()
        self.loss, self.dup = loss, dup
        self.rng = random.Random(seed)
        self.n = 0

    def session(self, name="g", player="p", port=None):
        self.n += 1
        addr = ("10.0.0.%d" % self.n, port or 5000 + self.n)
        ctx = SessionContext(lambda: None, lambda: ["10.0.0.1"], lambda n, e: None, random.Random(self.n))
        s = Session(FakeSock(self, addr), self.clock, ctx, name, player)
        self.nodes[addr] = s
        return s

    def step(self, dt=0.01):
        self.clock.t += dt
        batch, self.queue = list(self.queue), deque()
        for data, src, dst in batch:
            if src in self.dead or dst in self.dead or dst not in self.nodes:
                continue
            if self.rng.random() < self.loss:
                continue
            copies = 2 if self.rng.random() < self.dup else 1
            for _ in range(copies):
                self.nodes[dst].on_datagram(data, src)
        for addr, s in list(self.nodes.items()):
            if addr not in self.dead:
                s.tick()

    def run(self, seconds, dt=0.01):
        for _ in range(int(seconds / dt)):
            self.step(dt)

    def kill(self, s):
        self.dead.add(s.sock.addr)
