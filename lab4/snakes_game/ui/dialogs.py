from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .. import constants as C
from ..model import Config, validate_game_name, validate_player_name


class CreateGameDialog(tk.Toplevel):
    def __init__(self, master, player_name: str, server_available: bool,
                 on_local: Callable, on_server: Callable) -> None:
        super().__init__(master)
        self.title("Создать игру")
        self.resizable(False, False)
        self.transient(master)
        self._on_local, self._on_server = on_local, on_server
        self.name = tk.StringVar(value="my game")
        self.player = tk.StringVar(value=player_name)
        self.width = tk.IntVar(value=40)
        self.height = tk.IntVar(value=30)
        self.food = tk.IntVar(value=1)
        self.delay = tk.IntVar(value=1000)
        self.where = tk.StringVar(value="local")
        self.invite = tk.BooleanVar(value=False)

        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        rows = [
            ("Имя игры", ttk.Entry(f, textvariable=self.name, width=24)),
            ("Ваше имя", ttk.Entry(f, textvariable=self.player, width=24)),
            (f"Ширина ({C.FIELD_MIN}–{C.FIELD_MAX})",
             ttk.Spinbox(f, from_=C.FIELD_MIN, to=C.FIELD_MAX, textvariable=self.width, width=8)),
            (f"Высота ({C.FIELD_MIN}–{C.FIELD_MAX})",
             ttk.Spinbox(f, from_=C.FIELD_MIN, to=C.FIELD_MAX, textvariable=self.height, width=8)),
            (f"Запас еды ({C.FOOD_STATIC_MIN}–{C.FOOD_STATIC_MAX})",
             ttk.Spinbox(f, from_=C.FOOD_STATIC_MIN, to=C.FOOD_STATIC_MAX, textvariable=self.food, width=8)),
            (f"Интервал хода, мс ({C.STATE_DELAY_MIN}–{C.STATE_DELAY_MAX})",
             ttk.Spinbox(f, from_=C.STATE_DELAY_MIN, to=C.STATE_DELAY_MAX, increment=50,
                         textvariable=self.delay, width=8)),
        ]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            widget.grid(row=i, column=1, sticky="w", pady=3)
        r = len(rows)
        ttk.Radiobutton(f, text="Вести игру на этом компьютере (я — MASTER)", variable=self.where,
                        value="local").grid(row=r, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(f, text="Пригласить робота с сервера курса", variable=self.invite).grid(
            row=r + 1, column=0, columnspan=2, sticky="w", padx=22)
        rb = ttk.Radiobutton(f, text="Создать на сервере курса (параметры выберет сервер)",
                             variable=self.where, value="server")
        rb.grid(row=r + 2, column=0, columnspan=2, sticky="w")
        if not server_available:
            rb.state(["disabled"])
        self.error = ttk.Label(f, foreground="#d33", wraplength=330)
        self.error.grid(row=r + 3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        bar = ttk.Frame(f)
        bar.grid(row=r + 4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="Создать", command=self._submit).pack(side="right")
        ttk.Button(bar, text="Отмена", command=self.destroy).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self._submit())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()

    def _submit(self) -> None:
        try:
            game, player = self.name.get().strip(), self.player.get().strip()
            validate_game_name(game)
            validate_player_name(player)
            if self.where.get() == "server":
                self._on_server(game, player)
            else:
                cfg = Config(self.width.get(), self.height.get(), self.food.get(), self.delay.get())
                cfg.validate()
                self._on_local(game, player, cfg, self.invite.get())
        except (ValueError, tk.TclError) as e:
            self.error.config(text=str(e) if isinstance(e, ValueError) else "Введите числа в числовые поля")
            return
        self.destroy()
