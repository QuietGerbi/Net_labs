"""Надёжная доставка поверх UDP: ACK, повторы, окно дедупликации, Ping, связь с соседями."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from . import constants as C
from .messages import ProtocolError, envelope, serialize_checked
from .model import Endpoint
from .proto import snakes_pb2 as pb


class Link:
    """Состояние связи с одним соседом."""

    __slots__ = ("last_send", "last_recv", "max_req_seq")

    def __init__(self, now: float) -> None:
        self.last_send = now
        self.last_recv = now  # старт таймера связи
        self.max_req_seq = -1  # наибольший отправленный номер сообщения, требующего ответа


class Pending:
    __slots__ = ("msg", "ep", "sent_at", "key")

    def __init__(self, msg: "pb.GameMessage", ep: Endpoint, sent_at: float, key: Optional[str]):
        self.msg = msg
        self.ep = ep
        self.sent_at = sent_at
        self.key = key


class Outbox:
    """Исходящие сообщения сессии: нумерация, повторы каждые 100 мс, лимиты очереди."""

    def __init__(self, sock, clock: Callable[[], float]) -> None:
        self.sock = sock
        self.clock = clock
        self._seq = 0
        self.pending: Dict[int, Pending] = {}
        self.links: Dict[Endpoint, Link] = {}

    # ------------------------------------------------------------ счётчик
    def next_seq(self) -> int:
        if self._seq >= C.INT64_MAX:
            raise ProtocolError("Исчерпан счётчик msg_seq")
        seq = self._seq
        self._seq += 1
        return seq

    # ------------------------------------------------------------- связь
    def link(self, ep: Endpoint) -> Link:
        lk = self.links.get(ep)
        if lk is None:
            lk = self.links[ep] = Link(self.clock())
        return lk

    def touch(self, ep: Endpoint) -> None:
        """Любое корректное unicast-сообщение (включая ACK) обновляет таймер связи."""
        self.link(ep).last_recv = self.clock()

    def silence(self, ep: Endpoint) -> float:
        return self.clock() - self.link(ep).last_recv

    def idle(self, ep: Endpoint) -> float:
        return self.clock() - self.link(ep).last_send

    # --------------------------------------------------------- отправка
    def emit_raw(self, ep: Endpoint, data: bytes) -> None:
        self.sock.sendto(data, ep)
        self.link(ep).last_send = self.clock()

    def _emit(self, ep: Endpoint, msg: "pb.GameMessage") -> None:
        self.emit_raw(ep, serialize_checked(msg))

    def send(self, ep: Endpoint, msg: "pb.GameMessage", reliable: bool = True,
             key: Optional[str] = None) -> int:
        """Присваивает msg_seq и отправляет.

        reliable=True — сообщение ждёт ACK и повторяется. key задаёт «заменяемый» тип
        (state/steer/ping): новое сообщение вытесняет неподтверждённое старое.
        """
        msg.msg_seq = self.next_seq()
        if reliable:
            lk = self.link(ep)
            if key is not None:
                for seq in [s for s, p in self.pending.items() if p.ep == ep and p.key == key]:
                    del self.pending[seq]
            # Запрос мог выйти из окна дедупликации получателя: прекращаем его повторы.
            for seq in [s for s, p in self.pending.items()
                        if p.ep == ep and s <= msg.msg_seq - C.DEDUP_WINDOW]:
                del self.pending[seq]
            self._enforce_queue_limit(ep)
            lk.max_req_seq = max(lk.max_req_seq, msg.msg_seq)
            self.pending[msg.msg_seq] = Pending(msg, ep, self.clock(), key)
        self._emit(ep, msg)
        return msg.msg_seq

    def _enforce_queue_limit(self, ep: Endpoint) -> None:
        """Не более 64 неподтверждённых к соседу: вытесняем только заменяемые, операции не теряем."""
        mine = [(s, p) for s, p in self.pending.items() if p.ep == ep]
        excess = len(mine) - (C.MAX_PENDING_PER_PEER - 1)
        for seq, p in sorted(mine):
            if excess <= 0:
                break
            if p.key is not None:
                del self.pending[seq]
                excess -= 1

    def send_ack(self, ep: Endpoint, request: "pb.GameMessage", game_name: str,
                 sender_id: Optional[int], receiver_id: Optional[int]) -> bytes:
        """ACK копирует msg_seq запроса и не расходует счётчик отправителя."""
        ack = envelope(game_name, sender_id, receiver_id)
        ack.msg_seq = request.msg_seq
        ack.ack.SetInParent()
        data = serialize_checked(ack)
        self.emit_raw(ep, data)
        return data

    # ----------------------------------------------------- подтверждения
    def take(self, ep: Endpoint, seq: int) -> Optional[Pending]:
        p = self.pending.get(seq)
        if p is None or p.ep != ep:
            return None  # несопоставленный ACK игнорируется
        del self.pending[seq]
        return p

    def cancel(self, seq: int) -> None:
        self.pending.pop(seq, None)

    def drop_endpoint(self, ep: Endpoint) -> None:
        """Сосед удалён: его повторы прекращаются."""
        for seq in [s for s, p in self.pending.items() if p.ep == ep]:
            del self.pending[seq]
        self.links.pop(ep, None)

    def clear(self) -> None:
        self.pending.clear()

    def retarget(self, old: Endpoint, new: Endpoint, receiver_id: int) -> None:
        """Failover: неподтверждённые запросы к старому MASTER уходят новому (номер и тело те же)."""
        for seq in [s for s, p in self.pending.items() if p.ep == old]:
            p = self.pending[seq]
            if p.key == "ping":
                del self.pending[seq]
                continue
            p.ep = new
            p.msg.receiver_id = receiver_id
            p.sent_at = float("-inf")  # повторить немедленно
        self.links.pop(old, None)

    # ------------------------------------------------------------ повторы
    def retransmit(self) -> None:
        now = self.clock()
        for p in list(self.pending.values()):
            if now - p.sent_at >= C.RETRY_INTERVAL:
                p.sent_at = now
                self._emit(p.ep, p.msg)


class _Window:
    __slots__ = ("high", "responses")

    def __init__(self) -> None:
        self.high = -1
        self.responses: Dict[int, List[bytes]] = {}


class DedupTable:
    """Окно дедупликации в 1024 номера для каждого endpoint (внутри одной игры).

    Окно хранит номера max(0, H-1023)..H и ответы на них. Повтор получает прежний ответ,
    номер ниже окна игнорируется. Окна вышедших endpoint живут до конца игры.
    """

    def __init__(self, max_endpoints: int = C.MAX_DEDUP_ENDPOINTS) -> None:
        self.windows: Dict[Endpoint, _Window] = {}
        self.max_endpoints = max_endpoints

    def can_admit(self, ep: Endpoint) -> bool:
        return ep in self.windows or len(self.windows) < self.max_endpoints

    def check(self, ep: Endpoint, seq: int) -> Tuple[str, List[bytes]]:
        w = self.windows.get(ep)
        if w is None:
            return "new", []
        if seq in w.responses:
            return "dup", w.responses[seq]
        if seq < w.high - (C.DEDUP_WINDOW - 1):
            return "old", []
        return "new", []

    def record(self, ep: Endpoint, seq: int, responses: List[bytes]) -> None:
        w = self.windows.get(ep)
        if w is None:
            if len(self.windows) >= self.max_endpoints:
                return
            w = self.windows[ep] = _Window()
        w.responses[seq] = responses
        if seq > w.high:
            w.high = seq
            low = w.high - (C.DEDUP_WINDOW - 1)
            if len(w.responses) > C.DEDUP_WINDOW:
                for s in [s for s in w.responses if s < low]:
                    del w.responses[s]
