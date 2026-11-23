from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from . import theme
from ..node import GameRow, View
from ..proto import snakes_pb2 as pb

COLUMNS = (
    ("name", "Игра", 170), ("host", "MASTER", 150), ("players", "Участники", 80),
    ("field", "Поле", 70), ("food", "Еда", 45), ("delay", "Ход, мс", 65),
    ("join", "Мест", 60), ("src", "Источник", 110),
)


class LobbyFrame(ttk.Frame):
    def __init__(self, master, default_name: str, on_join: Callable, on_create: Callable) -> None:
        super().__init__(master, padding=12)
        self._on_join, self._on_create = on_join, on_create
        self._rows = ()

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Ваше имя:").pack(side="left")
        self.player = tk.StringVar(value=default_name)
        ttk.Entry(top, textvariable=self.player, width=22).pack(side="left", padx=8)
        self.server_label = tk.Label(top, anchor="e")
        self.server_label.pack(side="right")

        ttk.Label(self, text="Найденные игры (обновляется автоматически)",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(12, 4))
        self.tree = ttk.Treeview(self, columns=[c[0] for c in COLUMNS], show="headings", height=12)
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._join(pb.PLAYING))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(10, 0))
        self.btn_play = ttk.Button(bar, text="Играть", command=lambda: self._join(pb.PLAYING))
        self.btn_watch = ttk.Button(bar, text="Смотреть", command=lambda: self._join(pb.VIEWING))
        self.btn_create = ttk.Button(bar, text="Создать игру…", command=on_create)
        for b in (self.btn_play, self.btn_watch):
            b.pack(side="left", padx=(0, 8))
        self.btn_create.pack(side="right")
        self.status = ttk.Label(self, text="", foreground=theme.HINT)
        self.status.pack(anchor="w", pady=(8, 0))

    def player_name(self) -> str:
        return self.player.get().strip()

    def _selected(self) -> Optional[GameRow]:
        sel = self.tree.selection()
        if not sel:
            return None
        return next((r for r in self._rows if self._iid(r) == sel[0]), None)

    @staticmethod
    def _iid(r: GameRow) -> str:
        return f"{r.name}|{r.endpoint[0]}:{r.endpoint[1]}"

    def _join(self, status: int) -> None:
        row = self._selected()
        if row is not None:
            self._on_join(row, status)

    def update_view(self, view: View) -> None:
        text, color = theme.SERVER_TEXT[view.server_state]
        self.server_label.config(text=text, fg=color, bg=self.winfo_toplevel().cget("bg"))
        connecting = view.phase == "connecting"
        for b in (self.btn_play, self.btn_watch, self.btn_create):
            b.state(["disabled"] if connecting else ["!disabled"])
        self.status.config(text="Подключение к игре…" if connecting else "")
        if view.games == self._rows:
            return
        selected = self.tree.selection()
        self._rows = view.games
        self.tree.delete(*self.tree.get_children())
        for r in view.games:
            self.tree.insert("", "end", iid=self._iid(r), values=(
                r.name, f"{r.endpoint[0]}:{r.endpoint[1]}", f"{r.players}/6", f"{r.width}×{r.height}",
                r.food_static, r.state_delay_ms, "есть" if r.can_join else "нет", ", ".join(r.sources)))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
