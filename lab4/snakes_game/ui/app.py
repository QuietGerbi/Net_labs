from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme
from ..node import Node
from ..proto import snakes_pb2 as pb
from ..runner import NetworkRunner
from .dialogs import CreateGameDialog
from .game import GameFrame
from .lobby import LobbyFrame

POLL_MS = 40
MESSAGE_TTL_MS = 8000

KEYS = {
    "w": pb.UP, "up": pb.UP, "a": pb.LEFT, "left": pb.LEFT,
    "s": pb.DOWN, "down": pb.DOWN, "d": pb.RIGHT, "right": pb.RIGHT,
    "ц": pb.UP, "ф": pb.LEFT, "ы": pb.DOWN, "в": pb.RIGHT,
}


class App:
    def __init__(self, node: Node, default_name: str = "Player") -> None:
        self.node = node
        self.runner = NetworkRunner(node)
        self.root = tk.Tk()
        self.root.title("Змейка по сети")
        self.root.geometry("1040x620")
        self.root.minsize(820, 520)
        self.root.configure(bg=theme.BG)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.lobby = LobbyFrame(self.root, default_name, self._join, self._open_create)
        self.game = GameFrame(self.root, self._toggle_play, lambda: self.runner.send("leave"))
        self.message = tk.Label(self.root, anchor="w", bg=theme.BG, fg=theme.MUTED, padx=10, pady=4)
        self.message.pack(side="bottom", fill="x")
        self._shown = None
        self._seen_version = -1
        self._seen_error = self._seen_notice = None
        self._message_job = None
        self._closing = False

        self.root.bind_all("<KeyPress>", self._on_key)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        self.runner.start()
        self._show(self.lobby)
        self.root.after(POLL_MS, self._poll)
        self.root.mainloop()


    def _join(self, row, status: int) -> None:
        name = self.lobby.player_name()
        self.runner.send("join", row.name, row.endpoint, status, name)

    def _open_create(self) -> None:
        CreateGameDialog(
            self.root, self.lobby.player_name() or "Player", self.node.use_server,
            on_local=lambda g, p, cfg, inv: self.runner.send("create_local", g, p, cfg, inv),
            on_server=lambda g, p: self.runner.send("create_server", g, p))

    def _toggle_play(self) -> None:
        self.runner.send("status", not self.game.is_playing())

    def _on_key(self, event) -> None:
        if self._shown is not self.game or isinstance(event.widget, (tk.Entry, ttk.Entry)):
            return
        d = KEYS.get(event.keysym.lower()) or KEYS.get((event.char or "").lower())
        if d is not None:
            self.runner.send("steer", d)

    def _on_close(self) -> None:
        self._closing = True
        self.runner.send("quit")


    def _poll(self) -> None:
        if self._closing and not self.runner.alive:
            self.root.destroy()
            return
        view = self.runner.view
        if view.version != self._seen_version:
            self._seen_version = view.version
            self._apply(view)
        self.root.after(POLL_MS, self._poll)

    def _apply(self, view) -> None:
        if view.phase in ("game", "leaving") and view.world is not None:
            self._show(self.game)
            self.game.update_view(view)
        else:
            self._show(self.lobby)
            self.lobby.update_view(view)
        if view.error and view.error != self._seen_error:
            self._seen_error = view.error
            self._flash(view.error[1], theme.ERROR)
        elif view.notice and view.notice != self._seen_notice:
            self._seen_notice = view.notice
            self._flash(view.notice[1], theme.NOTICE)

    def _show(self, frame) -> None:
        if self._shown is frame:
            return
        if self._shown is not None:
            self._shown.pack_forget()
        frame.pack(fill="both", expand=True)
        self._shown = frame

    def _flash(self, text: str, color: str) -> None:
        self.message.config(text=text, fg=color)
        if self._message_job:
            self.root.after_cancel(self._message_job)
        self._message_job = self.root.after(
            MESSAGE_TTL_MS, lambda: self.message.config(text="", fg=theme.MUTED))
