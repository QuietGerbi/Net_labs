from __future__ import annotations

import random
from typing import Dict, List, Optional, Set

from . import constants as C
from .model import DIRECTION_VECTORS, OPPOSITE, Cell, Snake, World
from .proto import snakes_pb2 as pb

_DIRECTIONS = (pb.UP, pb.DOWN, pb.LEFT, pb.RIGHT)


def neighbor(cell: Cell, direction: int, width: int, height: int) -> Cell:
    vx, vy = DIRECTION_VECTORS[direction]
    return ((cell[0] + vx) % width, (cell[1] + vy) % height)


def is_reverse(snake: Snake, direction: int, width: int, height: int) -> bool:
    return neighbor(snake.cells[0], direction, width, height) == snake.cells[1]


def add_score(player, delta: int) -> None:
    player.score = min(C.INT32_MAX, player.score + delta)


def occupied_cells(world: World) -> Set[Cell]:
    return {c for s in world.snakes for c in s.cells}



def find_spawn(world: World, rng: random.Random) -> Optional[Snake]:
    if len(world.snakes) >= C.MAX_SNAKES:
        return None
    w, h = world.config.width, world.config.height
    r = C.SPAWN_SQUARE_RADIUS
    blocked: Set[Cell] = set()
    for s in world.snakes:
        for (x, y) in s.cells:
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    blocked.add(((x + dx) % w, (y + dy) % h))
    foods = set(world.foods)
    centers = [
        (x, y) for x in range(w) for y in range(h) if (x, y) not in blocked and (x, y) not in foods
    ]
    rng.shuffle(centers)
    for head in centers:
        dirs = list(_DIRECTIONS)
        rng.shuffle(dirs)
        for tail_dir in dirs:
            tail = neighbor(head, tail_dir, w, h)
            if tail in foods:
                continue
            return Snake(0, [head, tail], OPPOSITE[tail_dir])
    return None



def replenish_food(world: World, rng: random.Random) -> None:
    need = world.target_food() - len(world.foods)
    if need <= 0:
        return
    w, h = world.config.width, world.config.height
    busy = occupied_cells(world) | set(world.foods)
    free = [(x, y) for x in range(w) for y in range(h) if (x, y) not in busy]
    if not free:
        return
    world.foods.extend(rng.sample(free, min(need, len(free))))



def step(world: World, directions: Dict[int, int]) -> List[int]:
    w, h = world.config.width, world.config.height
    foods = set(world.foods)
    eaten: Set[Cell] = set()


    for s in world.snakes:
        d = directions.get(s.player_id, s.direction)
        if is_reverse(s, d, w, h):
            d = s.direction
        new_head = neighbor(s.cells[0], d, w, h)
        length_before = len(s.cells)
        s.cells.insert(0, new_head)
        s.direction = d
        if new_head in foods:
            eaten.add(new_head)
            owner = world.player(s.player_id)
            if owner is not None:
                add_score(owner, 1)
            if length_before >= C.MAX_SNAKE_LEN:
                s.cells.pop()
        else:
            s.cells.pop()


    occupancy: Dict[Cell, List[tuple]] = {}
    for i, s in enumerate(world.snakes):
        for j, c in enumerate(s.cells):
            occupancy.setdefault(c, []).append((i, j))
    dead: Set[int] = set()
    credits = [0] * len(world.snakes)
    for i, s in enumerate(world.snakes):
        for (k, j) in occupancy[s.cells[0]]:
            if k == i:
                if j != 0:
                    dead.add(i)
            else:
                dead.add(i)
                credits[k] += 1


    for i, s in enumerate(world.snakes):
        if credits[i]:
            owner = world.player(s.player_id)
            if owner is not None:
                add_score(owner, credits[i])


    dead_ids = [world.snakes[i].player_id for i in sorted(dead)]
    world.snakes = [s for i, s in enumerate(world.snakes) if i not in dead]
    for pid in dead_ids:
        owner = world.player(pid)
        if owner is not None:
            owner.status = pb.VIEWING
    world.foods = [c for c in world.foods if c not in eaten]
    return dead_ids
