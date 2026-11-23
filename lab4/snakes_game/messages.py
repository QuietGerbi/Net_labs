from __future__ import annotations

from typing import Optional

from . import constants as C
from .proto import snakes_pb2 as pb


class ProtocolError(Exception):
    pass


def envelope(game_name: Optional[str], sender_id: Optional[int] = None,
             receiver_id: Optional[int] = None) -> "pb.GameMessage":
    m = pb.GameMessage()
    m.msg_seq = 0
    m.protocol_version = C.PROTOCOL_VERSION
    if game_name is not None:
        m.game_name = game_name
    if sender_id is not None:
        m.sender_id = sender_id
    if receiver_id is not None:
        m.receiver_id = receiver_id
    return m


def parse_message(data: bytes) -> Optional["pb.GameMessage"]:
    if not data or len(data) > C.MAX_DATAGRAM_SIZE:
        return None
    m = pb.GameMessage()
    try:
        m.ParseFromString(data)
    except Exception:
        return None
    if m.protocol_version != C.PROTOCOL_VERSION or m.msg_seq < 0:
        return None
    if m.WhichOneof("Type") is None:
        return None
    return m


def serialize_checked(msg: "pb.GameMessage") -> bytes:
    data = msg.SerializeToString()
    if len(data) > C.MAX_DATAGRAM_SIZE:
        raise ProtocolError(f"Исходящее сообщение {len(data)} байт превышает {C.MAX_DATAGRAM_SIZE}")
    return data


def make_discover() -> "pb.GameMessage":
    m = envelope(None)
    m.discover.SetInParent()
    return m


def clip_error_text(text: str) -> str:
    raw = text.encode("utf-8")[: C.MAX_ERROR_BYTES]
    return raw.decode("utf-8", errors="ignore")
