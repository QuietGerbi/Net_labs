"""Преобразования World <-> protobuf и кодирование змейки «ключевыми точками»."""
from __future__ import annotations

from typing import List, Optional

from . import constants as C
from .model import (Cell, Config, Endpoint, Player, Snake, World, is_valid_ipv4,
                    validate_player_name)
from .proto import snakes_pb2 as pb


# ---------------------------------------------------------------- змейка
def _set_coord(coord, x: int, y: int) -> None:
    # Нулевые компоненты не записываем (значение по умолчанию — 0).
    if x:
        coord.x = x
    if y:
        coord.y = y


def _unit_step(a: int, b: int, size: int) -> int:
    d = (b - a) % size
    if d == 1:
        return 1
    if d == size - 1:
        return -1
    raise ValueError("соседние клетки змейки не смежны")


def encode_snake(snake: Snake, width: int, height: int) -> "pb.GameState.Snake":
    p = pb.GameState.Snake(player_id=snake.player_id, head_direction=snake.direction)
    hx, hy = snake.cells[0]
    _set_coord(p.points.add(), hx, hy)
    seg_dx = seg_dy = 0  # накапливаемый отрезок
    cur_step: Optional[tuple] = None
    for (ax, ay), (bx, by) in zip(snake.cells, snake.cells[1:]):
        if ax != bx:
            step = (_unit_step(ax, bx, width), 0)
        else:
            step = (0, _unit_step(ay, by, height))
        if step != cur_step and cur_step is not None:
            _set_coord(p.points.add(), seg_dx, seg_dy)
            seg_dx = seg_dy = 0
        cur_step = step
        seg_dx += step[0]
        seg_dy += step[1]
    if cur_step is not None:
        _set_coord(p.points.add(), seg_dx, seg_dy)
    return p


def decode_snake(p: "pb.GameState.Snake", width: int, height: int) -> Snake:
    if len(p.points) < 2:
        raise ValueError("у змейки меньше двух ключевых точек")
    hx, hy = p.points[0].x, p.points[0].y
    if not (0 <= hx < width and 0 <= hy < height):
        raise ValueError("голова вне поля")
    x, y = hx, hy
    cells: List[Cell] = [(x, y)]
    for off in p.points[1:]:
        dx, dy = off.x, off.y
        if (dx == 0) == (dy == 0):
            raise ValueError("смещение должно быть ненулевым и осевым")
        count = abs(dx or dy)
        sx = (dx > 0) - (dx < 0)
        sy = (dy > 0) - (dy < 0)
        if len(cells) + count > C.MAX_SNAKE_LEN:
            raise ValueError("змейка длиннее 32 клеток")
        for _ in range(count):
            x, y = x + sx, y + sy
            cells.append((x % width, y % height))
    if len(cells) < C.MIN_SNAKE_LEN:
        raise ValueError("змейка короче двух клеток")
    if len(set(cells)) != len(cells):
        raise ValueError("клетки змейки повторяются")
    if p.head_direction not in (pb.UP, pb.DOWN, pb.LEFT, pb.RIGHT):
        raise ValueError("неверное направление")
    return Snake(p.player_id, cells, p.head_direction)


# ---------------------------------------------------------------- игроки
def player_to_proto(p: Player, hide_endpoint: bool) -> "pb.GamePlayer":
    gp = pb.GamePlayer(name=p.name, id=p.id, role=p.role, score=p.score, status=p.status)
    if p.type != pb.HUMAN:
        gp.type = p.type
    if not hide_endpoint and p.ip is not None and p.port is not None:
        gp.ip_address = p.ip
        gp.port = p.port
    return gp


def players_to_proto(world: World, sender_id: Optional[int]) -> "pb.GamePlayers":
    """Endpoint отправителя опускается: получатель берёт его из UDP-пакета."""
    gps = pb.GamePlayers()
    for p in world.players:
        gps.players.append(player_to_proto(p, hide_endpoint=(p.id == sender_id)))
    return gps


# ---------------------------------------------------------------- состояние
def world_to_state(world: World, sender_id: Optional[int]) -> "pb.GameState":
    w, h = world.config.width, world.config.height
    st = pb.GameState(state_order=world.state_order, next_player_id=world.next_player_id)
    for s in world.snakes:
        st.snakes.append(encode_snake(s, w, h))
    for (x, y) in world.foods:
        _set_coord(st.foods.add(), x, y)
    st.players.CopyFrom(players_to_proto(world, sender_id))
    return st


def world_from_proto(st: "pb.GameState", config: Config, game_name: str,
                     sender_ep: Endpoint) -> World:
    """Разбирает и проверяет снимок; ValueError — снимок некорректен."""
    if st.state_order < 0:
        raise ValueError("отрицательный state_order")
    gps = st.players.players
    if len(gps) > C.MAX_PLAYERS:
        raise ValueError("слишком много игроков")
    players: List[Player] = []
    ids = set()
    masters = 0
    for gp in gps:
        if gp.id <= 0 or gp.id in ids:
            raise ValueError("неверный или повторный id игрока")
        validate_player_name(gp.name)
        if gp.score < 0:
            raise ValueError("отрицательные очки")
        ip = port = None
        if gp.HasField("ip_address"):
            if not is_valid_ipv4(gp.ip_address):
                raise ValueError("неверный IPv4-адрес")
            ip = gp.ip_address
        if gp.HasField("port"):
            if not 0 < gp.port < 65536:
                raise ValueError("неверный порт")
            port = gp.port
        if (ip is None) != (port is None):
            raise ValueError("endpoint игрока задан не полностью")
        player = Player(gp.id, gp.name, gp.role, gp.status, gp.score, gp.type, ip, port)
        if gp.role == pb.MASTER:
            masters += 1
            player.ip, player.port = sender_ep  # адрес отправителя берётся из UDP-пакета
        ids.add(gp.id)
        players.append(player)
    if masters != 1:
        raise ValueError("в состоянии должен быть ровно один MASTER")
    if st.next_player_id <= max(ids, default=0):
        raise ValueError("next_player_id не выше выданных id")

    if len(st.snakes) > C.MAX_SNAKES:
        raise ValueError("слишком много змей")
    by_id = {p.id: p for p in players}
    snakes: List[Snake] = []
    owners = set()
    for sp in st.snakes:
        owner = by_id.get(sp.player_id)
        if owner is None or owner.status != pb.PLAYING or sp.player_id in owners:
            raise ValueError("змейка без владельца со статусом PLAYING")
        owners.add(sp.player_id)
        snakes.append(decode_snake(sp, config.width, config.height))

    foods: List[Cell] = []
    for c in st.foods:
        if not (0 <= c.x < config.width and 0 <= c.y < config.height):
            raise ValueError("еда вне поля")
        foods.append((c.x, c.y))
    if len(foods) > config.width * config.height:
        raise ValueError("еды больше, чем клеток")

    return World(game_name, config, st.state_order, snakes, foods, players, st.next_player_id)
