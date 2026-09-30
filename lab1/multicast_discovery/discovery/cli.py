import sys
import signal

from .core import MulticastDiscovery


def parse_args(argv):
    if len(argv) < 2:
        print("Использование: python discovery.py <multicast-адрес> [порт] [интерфейс]")
        print("Примеры:")
        print("  python discovery.py 239.255.0.1")
        print("  python discovery.py ff02::1:1 60000")
        print("  python discovery.py ff02::1:1 60000 eth0")
        sys.exit(1)
    group = argv[1]
    port = 60000
    interface = None
    if len(argv) >= 3:
        try:
            port = int(argv[2])
        except ValueError:
            print(f"Некорректный порт: {argv[2]}", file=sys.stderr)
            sys.exit(1)
    if len(argv) >= 4:
        interface = argv[3]
    return group, port, interface


def main():
    group, port, interface = parse_args(sys.argv)
    try:
        app = MulticastDiscovery(group, port, interface)
    except (ValueError, TypeError, OSError) as e:
        print(f"Ошибка инициализации: {e}", file=sys.stderr)
        sys.exit(1)

    def handler(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    app.run()
    