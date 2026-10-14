import threading
import time


def format_speed(bytes_per_sec):
    value = float(bytes_per_sec)
    for unit in ("Б/с", "КиБ/с", "МиБ/с", "ГиБ/с"):
        if value < 1024 or unit == "ГиБ/с":
            return f"{value:.2f} {unit}"
        value /= 1024


class TransferStats:
    def __init__(self, label):
        self.label = label
        self.start = time.monotonic()
        self.last_time = self.start
        self.last_bytes = 0
        self.reported = False
        self._total = 0
        self._lock = threading.Lock()

    def add(self, n):
        with self._lock:
            self._total += n

    @property
    def total(self):
        with self._lock:
            return self._total


class SpeedMonitor(threading.Thread):
    def __init__(self, interval=3.0):
        super().__init__(name="speed-monitor", daemon=True)
        self.interval = interval
        self._active = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def register(self, label):
        stats = TransferStats(label)
        with self._lock:
            self._active.append(stats)
        return stats

    def unregister(self, stats):
        with self._lock:
            if stats in self._active:
                self._active.remove(stats)
                if not stats.reported:
                    self._report(stats, time.monotonic())

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.wait(0.2):
            now = time.monotonic()
            with self._lock:
                for stats in self._active:
                    if now - stats.last_time >= self.interval:
                        self._report(stats, now)

    def _report(self, stats, now):
        total = stats.total
        dt = max(now - stats.last_time, 1e-9)
        elapsed = max(now - stats.start, 1e-9)
        instant = (total - stats.last_bytes) / dt
        average = total / elapsed
        stats.last_time, stats.last_bytes, stats.reported = now, total, True
        print(f"[{stats.label}] мгновенная: {format_speed(instant)}, "
              f"средняя: {format_speed(average)}", flush=True)
