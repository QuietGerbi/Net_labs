"""Таймеры сессий на куче. Отмена ленивая: через счётчик поколений timer_gen."""

import heapq
import itertools
import time


class Timers:
    def __init__(self):
        self._heap = []
        self._seq = itertools.count()

    def set(self, s, delay):
        s.timer_gen += 1
        heapq.heappush(self._heap, (time.monotonic() + delay, next(self._seq), s, s.timer_gen))

    @staticmethod
    def cancel(s):
        s.timer_gen += 1

    def _discard_stale(self):
        while self._heap:
            _, _, s, gen = self._heap[0]
            if s.closed or gen != s.timer_gen:
                heapq.heappop(self._heap)
            else:
                return

    def next_timeout(self):
        """Сколько секунд ждать в select() (None — бесконечно)."""
        self._discard_stale()
        if not self._heap:
            return None
        return max(0.0, self._heap[0][0] - time.monotonic())

    def pop_expired(self):
        """Итератор по сессиям, чей таймер сработал."""
        now = time.monotonic()
        while self._heap and self._heap[0][0] <= now:
            _, _, s, gen = heapq.heappop(self._heap)
            if s.closed or gen != s.timer_gen:
                continue
            yield s
