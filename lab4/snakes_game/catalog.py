"""Единый список игр из двух источников (LAN multicast и сервер курса)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import constants as C
from .model import Config, Endpoint, utf8_len
from .proto import snakes_pb2 as pb

SOURCE_LAN = "LAN"
SOURCE_SERVER = "Сервер"


@dataclass
class GameEntry:
    name: str
    endpoint: Endpoint
    config: Config
    players: int
    can_join: bool
    seen: Dict[str, float] = field(default_factory=dict)  # источник -> время последнего анонса

    @property
    def key(self) -> Tuple[str, Endpoint]:
        return (self.name, self.endpoint)

    def sources(self, now: float) -> List[str]:
        return sorted(s for s, t in self.seen.items() if now - t <= C.ANNOUNCE_TTL)


class GameCatalog:
    """Записи объединяются по (game_name, endpoint MASTER) и устаревают независимо через 3 с."""

    def __init__(self) -> None:
        self._entries: Dict[Tuple[str, Endpoint], GameEntry] = {}

    def update(self, announcement: "pb.GameMessage", src: Endpoint, source: str, now: float) -> None:
        for g in announcement.announcement.games:
            if not g.game_name or utf8_len(g.game_name) > C.MAX_GAME_NAME_BYTES:
                continue
            try:
                cfg = Config.from_proto(g.config)
            except ValueError:
                continue
            key = (g.game_name, src)
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = GameEntry(g.game_name, src, cfg, 0, True)
            entry.config = cfg
            entry.players = len(g.players.players)
            entry.can_join = g.can_join
            entry.seen[source] = now

    def prune(self, now: float) -> None:
        for key in [k for k, e in self._entries.items() if not e.sources(now)]:
            del self._entries[key]

    def entries(self, now: float) -> List[GameEntry]:
        return sorted((e for e in self._entries.values() if e.sources(now)),
                      key=lambda e: (e.name, e.endpoint))

    def find(self, name: str, ep: Endpoint) -> Optional[GameEntry]:
        return self._entries.get((name, ep))

    def find_alternative(self, name: str, exclude: Endpoint, now: float) -> Optional[Endpoint]:
        """Другая запись с тем же game_name (поиск нового MASTER после его отказа)."""
        for e in self.entries(now):
            if e.name == name and e.endpoint != exclude:
                return e.endpoint
        return None
