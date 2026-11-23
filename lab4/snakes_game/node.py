from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import constants as C
from .catalog import SOURCE_LAN, SOURCE_SERVER, GameCatalog
from .messages import make_discover, parse_message, serialize_checked
from .model import Config, Endpoint, World, validate_game_name, validate_player_name
from .net.interfaces import local_ipv4_addresses
from .net.transport import MulticastReceiver, UdpSocket
from .proto import snakes_pb2 as pb
from .session import Phase, Session, SessionContext

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GameRow:

    name: str
    endpoint: Endpoint
    players: int
    width: int
    height: int
    food_static: int
    state_delay_ms: int
    can_join: bool
    sources: Tuple[str, ...]


@dataclass(frozen=True)
class View:

    version: int
    phase: str
    games: Tuple[GameRow, ...]
    server_state: str
    world: Optional[World]
    my_id: Optional[int]
    is_master: bool
    status_pending: bool
    notice: Optional[Tuple[int, str]]
    error: Optional[Tuple[int, str]]


class Node:
    def __init__(self, server_host: str = C.COURSE_SERVER_HOST, server_port: int = C.COURSE_SERVER_PORT,
                 use_server: bool = True, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.use_server = use_server
        self.server_host, self.server_port = server_host, server_port
        self.server_ip: Optional[str] = None
        self._last_server_announce = float("-inf")

        self.catalog = GameCatalog()
        try:
            self.mcast: Optional[MulticastReceiver] = MulticastReceiver()
        except OSError as e:
            log.warning("Multicast недоступен: %s", e)
            self.mcast = None
        self.lobby_sock = UdpSocket()
        self._ifaces: List[str] = []
        self._ifaces_at = float("-inf")
        self._last_discover = float("-inf")
        self._discover_seq = 0

        self.session: Optional[Session] = None
        self.quit_requested = False
        self._quit_deadline = 0.0
        self._ctx = SessionContext(
            server_ep=lambda: self.server_ep,
            interfaces=lambda: self._ifaces,
            find_alternative=lambda name, ex: self.catalog.find_alternative(name, ex, self.clock()),
            rng=random.Random(),
        )

        self._notice: Optional[Tuple[int, str]] = None
        self._error: Optional[Tuple[int, str]] = None
        self._counter = 0
        self._view_key = None
        self._seen_session_notice = 0
        self._version = 0
        self.view = self._build_view(self.clock())


    @property
    def server_ep(self) -> Optional[Endpoint]:
        if not self.use_server or not self.server_ip:
            return None
        return (self.server_ip, self.server_port)

    def _server_state(self, now: float) -> str:
        if not self.use_server:
            return "off"
        if self.server_ip is None:
            return "resolving"
        return "ok" if now - self._last_server_announce <= C.ANNOUNCE_TTL else "silent"


    def sockets(self) -> list:
        socks = [self.lobby_sock]
        if self.mcast is not None:
            socks.append(self.mcast)
        if self.session is not None:
            socks.append(self.session.sock)
        return socks

    def read(self, sock) -> None:
        now = self.clock()
        for data, ep in sock.recv_all():
            try:
                if self.session is not None and sock is self.session.sock:
                    self.session.on_datagram(data, ep)
                else:
                    self._on_lobby_datagram(data, ep, now, from_multicast=sock is self.mcast)
            except Exception:
                log.exception("Ошибка обработки датаграммы от %s", ep)

    def _on_lobby_datagram(self, data: bytes, ep: Endpoint, now: float, from_multicast: bool) -> None:
        msg = parse_message(data)
        if msg is None or msg.WhichOneof("Type") != "announcement":
            return
        if from_multicast:
            source = SOURCE_LAN
        elif ep == self.server_ep:
            source = SOURCE_SERVER
            self._last_server_announce = now
        else:
            source = SOURCE_LAN
        self.catalog.update(msg, ep, source, now)


    def handle_command(self, cmd: tuple) -> None:
        name, args = cmd[0], cmd[1:]
        try:
            getattr(self, "_cmd_" + name)(*args)
        except ValueError as e:
            self._set_error_or_notice(str(e))
        except OSError as e:
            self._set_error_or_notice(f"Сетевая ошибка: {e}")

    def _set_error_or_notice(self, text: str) -> None:
        self._counter += 1
        self._notice = (self._counter, text)

    def _busy(self) -> bool:
        if self.session is not None:
            self._set_error_or_notice("Сначала выйдите из текущей игры")
            return True
        return False

    def _new_session(self, game_name: str, player_name: str) -> Session:
        validate_game_name(game_name)
        validate_player_name(player_name)
        return Session(UdpSocket(), self.clock, self._ctx, game_name, player_name)

    def _cmd_create_local(self, game_name: str, player_name: str, config: Config, invite_server: bool) -> None:
        if self._busy():
            return
        config.validate()
        s = self._new_session(game_name, player_name)
        try:
            s.start_as_master(config, invite_server)
        except Exception:
            s.sock.close()
            raise
        self._error = None
        self.session = s

    def _cmd_create_server(self, game_name: str, player_name: str) -> None:
        if self._busy():
            return
        ep = self.server_ep
        if ep is None:
            raise ValueError("Адрес сервера курса пока не определён")
        s = self._new_session(game_name, player_name)
        s.start_as_client(ep, pb.PLAYING, None)
        self._error = None
        self.session = s

    def _cmd_join(self, game_name: str, endpoint: Endpoint, status: int, player_name: str) -> None:
        if self._busy():
            return
        entry = self.catalog.find(game_name, endpoint)
        if entry is None:
            raise ValueError("Игра исчезла из списка")
        s = self._new_session(game_name, player_name)
        s.start_as_client(endpoint, status, entry.config)
        self._error = None
        self.session = s

    def _cmd_status(self, playing: bool) -> None:
        if self.session is not None:
            self.session.request_status(playing)

    def _cmd_steer(self, direction: int) -> None:
        if self.session is not None:
            self.session.steer(direction)

    def _cmd_leave(self) -> None:
        if self.session is not None:
            self.session.leave()

    def _cmd_quit(self) -> None:
        self.quit_requested = True
        self._quit_deadline = self.clock() + 2 * C.LEAVE_TIMEOUT
        if self.session is not None:
            self.session.leave()

    def should_stop(self) -> bool:
        return self.quit_requested and (self.session is None or self.clock() >= self._quit_deadline)


    def tick(self) -> None:
        now = self.clock()
        if now - self._ifaces_at >= C.IFACE_REFRESH_INTERVAL:
            self._ifaces = local_ipv4_addresses()
            self._ifaces_at = now
            if self.mcast is not None:
                self.mcast.join_interfaces(self._ifaces)
        self.catalog.prune(now)


        if (self.session is None or self.session.wants_discovery) and self.server_ep is not None:
            if now - self._last_discover >= C.DISCOVER_INTERVAL:
                self._last_discover = now
                m = make_discover()
                m.msg_seq = self._discover_seq
                self._discover_seq += 1
                self.lobby_sock.sendto(serialize_checked(m), self.server_ep)

        if self.session is not None:
            self.session.tick()
            self._pull_session_notice()
            if self.session.closed:
                self._finish_session()
        self._publish(now)

    def _pull_session_notice(self) -> None:
        notices = self.session.notices
        if notices and notices[-1][0] > self._seen_session_notice:
            self._seen_session_notice = notices[-1][0]
            self._set_error_or_notice(notices[-1][1])

    def _finish_session(self) -> None:
        s = self.session
        self.session = None
        self._seen_session_notice = 0
        s.sock.close()
        if s.error:
            self._counter += 1
            self._error = (self._counter, s.error)
        log.info("Сессия закрыта (%s)", s.error or "штатно")

    def shutdown(self) -> None:
        if self.session is not None:
            self.session.sock.close()
            self.session = None
        self.lobby_sock.close()
        if self.mcast is not None:
            self.mcast.close()


    def _games(self, now: float) -> Tuple[GameRow, ...]:
        return tuple(
            GameRow(e.name, e.endpoint, e.players, e.config.width, e.config.height,
                    e.config.food_static, e.config.state_delay_ms, e.can_join, tuple(e.sources(now)))
            for e in self.catalog.entries(now)
        )

    def _build_view(self, now: float) -> View:
        s = self.session
        phase = "lobby" if s is None else s.phase
        return View(
            version=self._version,
            phase=phase,
            games=self._games(now) if s is None or s.wants_discovery else (),
            server_state=self._server_state(now),
            world=s.snapshot() if s is not None else None,
            my_id=s.my_id if s is not None else None,
            is_master=bool(s and s.is_master),
            status_pending=bool(s and not s.is_master and s.status_pending),
            notice=self._notice,
            error=self._error,
        )

    def _publish(self, now: float) -> None:
        s = self.session
        games = self._games(now) if s is None or s.wants_discovery else ()
        key = (None if s is None else (s.version, s.phase), games, self._server_state(now),
               self._notice, self._error)
        if key == self._view_key:
            return
        self._view_key = key
        self._version += 1
        self.view = self._build_view(now)
