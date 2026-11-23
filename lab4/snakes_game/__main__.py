from __future__ import annotations

import argparse
import logging
import sys

from . import constants as C
from .node import Node


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="snakes_game", description="Сетевая «Змейка» (протокол v2)")
    p.add_argument("--server", default=f"{C.COURSE_SERVER_HOST}:{C.COURSE_SERVER_PORT}",
                   metavar="HOST[:PORT]", help="сервер курса (по умолчанию %(default)s)")
    p.add_argument("--no-server", action="store_true", help="не опрашивать сервер курса (только LAN)")
    p.add_argument("--name", default="Player", help="имя игрока по умолчанию")
    p.add_argument("--debug", action="store_true", help="подробный лог в stderr")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host, _, port = args.server.partition(":")
    try:
        node = Node(host, int(port) if port else C.COURSE_SERVER_PORT, use_server=not args.no_server)
    except (ValueError, OSError) as e:
        print(f"Не удалось запустить: {e}", file=sys.stderr)
        return 1
    try:
        from .ui.app import App
    except ImportError as e:
        print("Не найден tkinter (в Linux: sudo apt install python3-tk).", e, file=sys.stderr)
        return 1
    App(node, args.name).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
