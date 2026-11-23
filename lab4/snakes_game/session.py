from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import constants as C
from .client_logic import ClientMixin
from .master_logic import MasterMixin
from .messages import ProtocolError, parse_message
from .model import Config, Endpoint, World
from .proto import snakes_pb2 as pb
from .reliable import DedupTable, Outbox

log = logging.getLogger(__name__)


class Phase:
    CONNECTING = "connecting"
    ACTIVE = "game"
    LEAVING = "leaving"
    CLOSED = "closed"


@dataclass
class SessionContext:

    server_ep: Callable[[], Optional[Endpoint]]
    interfaces: Callable[[], List[str]]
    find_alternative: Callable[[str, Endpoint], Optional[Endpoint]]
    rng: random.Random


class Session(MasterMixin, ClientMixin):
    def __init__(self, sock, clock: Callable[[], float], ctx: SessionContext,
                 game_name: str, player_name: str) -> None:
        self.sock = sock
        self.clock = clock
        self.ctx = ctx
        self.rng = ctx.rng
        self.game_name = game_name
        self.player_name = player_name

        self.out = Outbox(sock, clock)
        self.dedup = DedupTable()
        self.phase = Phase.CONNECTING
        self.is_master = False
        self.config: Optional[Config] = None
        self.world: Optional[World] = None
        self.my_id: Optional[int] = None
        self.error: Optional[str] = None
        self.version = 0
        self.notices: List[Tuple[int, str]] = []
        self._notice_counter = 0
        self._init_master_fields()
        self._init_client_fields()


    @property
    def wants_discovery(self) -> bool:
        return self.phase == Phase.CONNECTING and not self.is_master and not self.join_acked

    @property
    def closed(self) -> bool:
        return self.phase == Phase.CLOSED

    def snapshot(self) -> Optional[World]:
        return self.world.clone() if self.world is not None else None

    def my_player(self):
        return self.world.player(self.my_id) if self.world and self.my_id else None

    def notice(self, text: str) -> None:
        self._notice_counter += 1
        self.notices.append((self._notice_counter, text))
        del self.notices[:-20]
        self.version += 1

    def fail(self, text: str) -> None:
        log.warning("Сессия завершена с ошибкой: %s", text)
        self.error = text
        self.phase = Phase.CLOSED
        self.version += 1

    def steer(self, direction: int) -> None:
        if self.phase != Phase.ACTIVE:
            return
        if self.is_master:
            self._m_local_steer(direction)
        else:
            self._c_steer(direction)

    def request_status(self, playing: bool) -> None:
        if self.phase != Phase.ACTIVE:
            return
        if self.is_master:
            self._m_local_status(playing)
        else:
            self._c_request_status(playing)

    def leave(self) -> None:
        if self.phase in (Phase.LEAVING, Phase.CLOSED):
            return
        now = self.clock()
        try:
            if self.is_master:
                self._m_begin_leave(now)
            else:
                self._c_begin_leave(now)
        except ProtocolError as e:
            self.fail(str(e))


    def tick(self) -> None:
        if self.phase == Phase.CLOSED:
            return
        now = self.clock()
        try:
            if self.is_master:
                self._m_tick(now)
            else:
                self._c_tick(now)
        except ProtocolError as e:
            self.fail(str(e))

    def on_datagram(self, data: bytes, ep: Endpoint) -> None:
        if self.phase == Phase.CLOSED:
            return
        msg = parse_message(data)
        if msg is None:
            return
        now = self.clock()
        t = msg.WhichOneof("Type")
        try:
            if t == "discover":
                self._on_discover(ep)
                return
            if t == "announcement":
                self._on_announcement(msg, ep, now)
                return
            if not msg.HasField("game_name") or msg.game_name != self.game_name:
                return
            if t == "ack":
                self._on_ack(msg, ep, now)
                return
            if self.phase == Phase.LEAVING:
                return
            if self.is_master:
                self._master_receive(msg, ep, t, now)
            else:
                self._client_receive(msg, ep, t, now)
        except ProtocolError as e:
            self.fail(str(e))


    def _reply_ack(self, ep: Endpoint, req: "pb.GameMessage",
                   receiver_id: Optional[int] = None) -> bytes:
        if receiver_id is None and req.HasField("sender_id"):
            receiver_id = req.sender_id
        return self.out.send_ack(ep, req, self.game_name, self.my_id, receiver_id)

    def _on_ack(self, msg: "pb.GameMessage", ep: Endpoint, now: float) -> None:
        if not self._ack_sender_ok(msg, ep):
            return
        known = self._is_known_neighbor(ep)
        if known:
            self.out.touch(ep)
        pending = self.out.take(ep, msg.msg_seq)
        if pending is None:
            return
        if not known:
            self.out.touch(ep)
        self._after_ack(pending, msg, now)

    def _after_ack(self, pending, ack: "pb.GameMessage", now: float) -> None:
        if self.phase == Phase.LEAVING and pending.msg.msg_seq == self.leave_seq:
            self._on_leave_ack(now)
            return
        if not self.is_master:
            self._c_after_ack(pending, ack, now)
