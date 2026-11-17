"""Сетевой поток и поток-резолвер DNS. Число потоков фиксировано: 2 (+ поток интерфейса)."""
from __future__ import annotations

import logging
import queue
import select
import socket
import threading

from . import constants as C
from .node import Node, View

log = logging.getLogger(__name__)


class NetworkRunner:
    def __init__(self, node: Node) -> None:
        self.node = node
        self._commands: "queue.Queue[tuple]" = queue.Queue()
        self._stop = threading.Event()
        self._net = threading.Thread(target=self._net_loop, name="snakes-net", daemon=True)
        self._dns = threading.Thread(target=self._dns_loop, name="snakes-dns", daemon=True)

    @property
    def view(self) -> View:
        return self.node.view

    @property
    def alive(self) -> bool:
        return self._net.is_alive()

    def start(self) -> None:
        self._net.start()
        if self.node.use_server:
            self._dns.start()

    def send(self, *command) -> None:
        """Потокобезопасная команда сетевому потоку."""
        self._commands.put(command)

    def join(self, timeout: float = 3.0) -> None:
        self._net.join(timeout)

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ потоки
    def _net_loop(self) -> None:
        node = self.node
        while not self._stop.is_set() and not node.should_stop():
            try:
                readable, _, _ = select.select(node.sockets(), [], [], C.LOOP_SELECT_TIMEOUT)
                while True:
                    try:
                        cmd = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    node.handle_command(cmd)
                for sock in readable:
                    node.read(sock)
                node.tick()
            except Exception:
                log.exception("Ошибка в сетевом цикле")
        node.shutdown()
        self._stop.set()

    def _dns_loop(self) -> None:
        """DNS-имя сервера разрешается в IPv4 отдельным потоком, чтобы не блокировать сеть."""
        while not self._stop.is_set():
            wait = 5.0
            try:
                self.node.server_ip = socket.gethostbyname(self.node.server_host)
                wait = 60.0
            except OSError as e:
                log.warning("Не удалось разрешить %s: %s", self.node.server_host, e)
            self._stop.wait(wait)
