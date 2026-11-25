import sys

from proxy import Proxy
from resolver_config import parse_hostport, system_resolver


def main():
    if len(sys.argv) not in (2, 3):
        print("Использование: main.py <port> [dns_ip:port]", file=sys.stderr)
        return 2
    try:
        port = int(sys.argv[1])
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("Некорректный порт", file=sys.stderr)
        return 2
    if len(sys.argv) == 3:
        try:
            resolver = parse_hostport(sys.argv[2])
        except ValueError:
            print("DNS-резолвер должен быть в формате IPv4:port", file=sys.stderr)
            return 2
    else:
        try:
            resolver = system_resolver()
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 2
    proxy = Proxy(port, resolver)
    print(f"SOCKS5-прокси слушает порт {port}, DNS: {resolver[0]}:{resolver[1]}", file=sys.stderr)
    try:
        proxy.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
