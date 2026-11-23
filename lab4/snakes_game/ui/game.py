from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from . import theme
from ..model import World
from ..node import View
from ..proto import snakes_pb2 as pb


class GameFrame(ttk.Frame):
    def __init__(self, master, on_toggle_play: Callable, on_leave: Callable) -> None:
        super().__init__(master, padding=8)
        self._world: Optional[World] = None
        self._my_id: Optional[int] = None
        self._on_toggle_play = on_toggle_play

        self.canvas = tk.Canvas(self, bg=theme.BG, highlightthickness=0, width=640, height=480)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw())

        side = ttk.Frame(self, padding=(12, 0, 0, 0))
        side.pack(side="right", fill="y")
        self.title = ttk.Label(side, font=("TkDefaultFont", 13, "bold"))
        self.title.pack(anchor="w")
        self.me = ttk.Label(side)
        self.me.pack(anchor="w", pady=(2, 8))

        cols = (("name", "Игрок", 120), ("score", "Очки", 55), ("role", "Роль", 75), ("status", "Статус", 70))
        self.tree = ttk.Treeview(side, columns=[c[0] for c in cols], show="headings", height=7)
        for key, title, w in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, anchor="w")
        self.tree.pack(fill="x")
        self.food = ttk.Label(side)
        self.food.pack(anchor="w", pady=8)

        self.btn_play = ttk.Button(side, command=on_toggle_play)
        self.btn_play.pack(fill="x", pady=(4, 4))
        ttk.Button(side, text="Выйти из игры", command=on_leave).pack(fill="x")
        ttk.Label(side, foreground=theme.HINT, justify="left", wraplength=290, text=(
            "Управление: W A S D или стрелки.\n"
            "«Смотреть» убирает змейку, но оставляет вас в игре; "
            "«Выйти из игры» отключает полностью.\n"
            "Роль (MASTER/DEPUTY/NORMAL) — сетевая, статус — играете или смотрите.")).pack(
            anchor="w", pady=(14, 0))

    def update_view(self, view: View) -> None:
        w = view.world
        if w is None:
            return
        self._world, self._my_id = w, view.my_id
        me = w.player(view.my_id)
        self.title.config(text=f"Игра «{w.game_name}»  {w.config.width}×{w.config.height}")
        if me:
            self.me.config(text=f"Вы: {me.name} · {theme.ROLE_TEXT[me.role]} · {theme.STATUS_TEXT[me.status]}")
        self.tree.delete(*self.tree.get_children())
        for p in sorted(w.players, key=lambda p: (-p.score, p.id)):
            name = p.name + (" (вы)" if p.id == view.my_id else "")
            self.tree.insert("", "end", values=(name, p.score, theme.ROLE_TEXT[p.role], theme.STATUS_TEXT[p.status]))
        self.food.config(text=f"Еда: {len(w.foods)} на поле, цель {w.target_food()} "
                              f"(запас {w.config.food_static} + змей {len(w.snakes)})")
        if view.phase == "leaving":
            self.btn_play.state(["disabled"])
            self.btn_play.config(text="Выходим…")
        else:
            playing = me is not None and me.status == pb.PLAYING
            self.btn_play.config(text="Смотреть (прекратить играть)" if playing else "Играть (вернуться к игре)")
            self.btn_play.state(["disabled"] if view.status_pending else ["!disabled"])
        self._draw()

    def is_playing(self) -> bool:
        me = self._world.player(self._my_id) if self._world else None
        return me is not None and me.status == pb.PLAYING


    def _draw(self) -> None:
        c, w = self.canvas, self._world
        c.delete("all")
        if w is None:
            return
        cw, ch = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        gw, gh = w.config.width, w.config.height
        cell = max(3, min(cw // gw, ch // gh))
        ox, oy = (cw - cell * gw) // 2, (ch - cell * gh) // 2
        c.create_rectangle(ox, oy, ox + cell * gw, oy + cell * gh, fill=theme.FIELD, outline=theme.BORDER)
        if cell >= 10:
            for x in range(1, gw):
                c.create_line(ox + x * cell, oy, ox + x * cell, oy + gh * cell, fill=theme.GRID)
            for y in range(1, gh):
                c.create_line(ox, oy + y * cell, ox + gw * cell, oy + y * cell, fill=theme.GRID)
        pad = max(1, cell // 8)
        for (x, y) in w.foods:
            c.create_oval(ox + x * cell + pad, oy + y * cell + pad, ox + (x + 1) * cell - pad,
                          oy + (y + 1) * cell - pad, fill=theme.FOOD, outline="")
        for s in w.snakes:
            color = theme.color_for(s.player_id)
            mine = s.player_id == self._my_id
            for i, (x, y) in enumerate(s.cells):
                x0, y0 = ox + x * cell, oy + y * cell
                if i == 0:
                    c.create_rectangle(x0, y0, x0 + cell, y0 + cell, fill=color,
                                       outline="#ffffff" if mine else "#000000", width=2 if cell > 8 else 1)
                    self._eye(c, s.direction, x0, y0, cell)
                else:
                    c.create_rectangle(x0 + pad, y0 + pad, x0 + cell - pad, y0 + cell - pad,
                                       fill=color, outline="")

    @staticmethod
    def _eye(c, direction: int, x0: int, y0: int, cell: int) -> None:
        cx, cy, d = x0 + cell / 2, y0 + cell / 2, cell / 4
        dx, dy = {pb.UP: (0, -1), pb.DOWN: (0, 1), pb.LEFT: (-1, 0), pb.RIGHT: (1, 0)}[direction]
        r = max(1, cell / 8)
        c.create_oval(cx + dx * d - r, cy + dy * d - r, cx + dx * d + r, cy + dy * d + r, fill="#101010", outline="")
