"""Цвета и подписи интерфейса."""
from ..proto import snakes_pb2 as pb

BG = "#1b1d24"
PANEL = "#242732"
FIELD = "#12141a"
GRID = "#1d2029"
BORDER = "#4a4f63"
TEXT = "#e8e9ee"
MUTED = "#9aa0b4"
HINT = "#555a6b"  # для ttk-подписей на светлой панели
FOOD = "#ff5d73"
ERROR = "#ff6b6b"
NOTICE = "#ffc857"

PALETTE = ["#4cc9f0", "#80ed99", "#ffd166", "#c77dff", "#ff9f68", "#6ee7d8"]


def color_for(player_id: int) -> str:
    return PALETTE[(player_id - 1) % len(PALETTE)]


ROLE_TEXT = {pb.MASTER: "MASTER", pb.DEPUTY: "DEPUTY", pb.NORMAL: "NORMAL"}
STATUS_TEXT = {pb.PLAYING: "играет", pb.VIEWING: "смотрит"}
SERVER_TEXT = {
    "off": ("сервер курса отключён", MUTED),
    "resolving": ("сервер курса: определяем адрес…", NOTICE),
    "silent": ("сервер курса: нет ответа (работает только LAN)", NOTICE),
    "ok": ("сервер курса: на связи", "#80ed99"),
}
