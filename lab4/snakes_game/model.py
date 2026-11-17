"""Модель данных игры. Не зависит ни от сети, ни от интерфейса."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import constants as C
from .proto import snakes_pb2 as pb

Cell = Tuple[int, int]
Endpoint = Tuple[str, int]

DIRECTION_VECTORS = {
    pb.UP: (0, -1),
    pb.DOWN: (0, 1),
    pb.LEFT: (-1, 0),
    pb.RIGHT: (1, 0),
}
OPPOSITE = {pb.UP: pb.DOWN, pb.DOWN: pb.UP, pb.LEFT: pb.RIGHT, pb.RIGHT: pb.LEFT}

ROLE_NAMES = {pb.NORMAL: "NORMAL", pb.MASTER: "MASTER", pb.DEPUTY: "DEPUTY"}
STATUS_NAMES = {pb.PLAYING: "PLAYING", pb.VIEWING: "VIEWING"}


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def validate_player_name(name: str) -> None:
    if not name or utf8_len(name) > C.MAX_PLAYER_NAME_BYTES:
        raise ValueError(f"Имя игрока: 1..{C.MAX_PLAYER_NAME_BYTES} байт UTF-8")


def validate_game_name(name: str) -> None:
    if not name or utf8_len(name) > C.MAX_GAME_NAME_BYTES:
        raise ValueError(f"Имя игры: 1..{C.MAX_GAME_NAME_BYTES} байт UTF-8")


def is_valid_ipv4(text: str) -> bool:
    """Четыре десятичных октета без ведущих нулей, до 15 ASCII-байт."""
    if not text or len(text) > 15 or not text.isascii():
        return False
    parts = text.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part[0] == "0") or int(part) > 255:
            return False
    return True


@dataclass
class Config:
    width: int = 40
    height: int = 30
    food_static: int = 1
    state_delay_ms: int = 1000

    def validate(self) -> None:
        if not C.FIELD_MIN <= self.width <= C.FIELD_MAX:
            raise ValueError(f"Ширина поля: {C.FIELD_MIN}..{C.FIELD_MAX}")
        if not C.FIELD_MIN <= self.height <= C.FIELD_MAX:
            raise ValueError(f"Высота поля: {C.FIELD_MIN}..{C.FIELD_MAX}")
        if not C.FOOD_STATIC_MIN <= self.food_static <= C.FOOD_STATIC_MAX:
            raise ValueError(f"Запас еды: {C.FOOD_STATIC_MIN}..{C.FOOD_STATIC_MAX}")
        if not C.STATE_DELAY_MIN <= self.state_delay_ms <= C.STATE_DELAY_MAX:
            raise ValueError(f"Интервал хода: {C.STATE_DELAY_MIN}..{C.STATE_DELAY_MAX} мс")

    @classmethod
    def from_proto(cls, p: "pb.GameConfig") -> "Config":
        # Отсутствующие optional-поля дают значения по умолчанию из схемы.
        cfg = cls(p.width, p.height, p.food_static, p.state_delay_ms)
        cfg.validate()
        return cfg

    def to_proto(self) -> "pb.GameConfig":
        return pb.GameConfig(
            width=self.width,
            height=self.height,
            food_static=self.food_static,
            state_delay_ms=self.state_delay_ms,
        )


@dataclass
class Player:
    id: int
    name: str
    role: int
    status: int
    score: int = 0
    type: int = pb.HUMAN
    ip: Optional[str] = None
    port: Optional[int] = None

    @property
    def endpoint(self) -> Optional[Endpoint]:
        if self.ip is None or self.port is None:
            return None
        return (self.ip, self.port)


@dataclass
class Snake:
    player_id: int
    cells: List[Cell]  # голова первой; все клетки тела, нормализованные по тору
    direction: int

    @property
    def head(self) -> Cell:
        return self.cells[0]


@dataclass
class World:
    """Полное состояние игры: GameState + конфиг + имя игры."""

    game_name: str
    config: Config
    state_order: int = 0
    snakes: List[Snake] = field(default_factory=list)
    foods: List[Cell] = field(default_factory=list)
    players: List[Player] = field(default_factory=list)
    next_player_id: int = 1

    # --- запросы ---
    def player(self, player_id: Optional[int]) -> Optional[Player]:
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def player_at(self, ep: Endpoint) -> Optional[Player]:
        for p in self.players:
            if p.endpoint == ep:
                return p
        return None

    def snake_of(self, player_id: int) -> Optional[Snake]:
        for s in self.snakes:
            if s.player_id == player_id:
                return s
        return None

    def master(self) -> Optional[Player]:
        return next((p for p in self.players if p.role == pb.MASTER), None)

    def deputy(self) -> Optional[Player]:
        return next((p for p in self.players if p.role == pb.DEPUTY), None)

    def target_food(self) -> int:
        return self.config.food_static + len(self.snakes)

    # --- копирование (снимок для интерфейса) ---
    def clone(self) -> "World":
        return World(
            game_name=self.game_name,
            config=dataclasses.replace(self.config),
            state_order=self.state_order,
            snakes=[Snake(s.player_id, list(s.cells), s.direction) for s in self.snakes],
            foods=list(self.foods),
            players=[dataclasses.replace(p) for p in self.players],
            next_player_id=self.next_player_id,
        )
