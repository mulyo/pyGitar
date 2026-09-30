"""Pendaftaran pintasan keyboard di QMainWindow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow


def register_shortcuts(
    window: QMainWindow,
    *,
    on_play_pause: Callable[[], None],
    on_stop: Callable[[], None],
    on_seek_back: Callable[[], None],
    on_seek_fwd: Callable[[], None],
    on_speed_up: Callable[[], None],
    on_speed_down: Callable[[], None],
    on_open_file: Callable[[], None],
    on_zoom_in: Callable[[], None],
    on_zoom_out: Callable[[], None],
    on_add_marker: Callable[[], None],
    on_toggle_loop: Callable[[], None],
) -> list[QShortcut]:
    """Daftarkan pintasan keyboard dan return list-nya (untuk simpan reference)."""

    def mk(seq: str, cb: Callable[[], None]) -> QShortcut:
        sc = QShortcut(QKeySequence(seq), window)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(cb)
        return sc

    shortcuts = [
        mk("Space", on_play_pause),
        mk("Ctrl+S", on_stop),
        mk("Ctrl+O", on_open_file),
        mk("Left", on_seek_back),
        mk("Right", on_seek_fwd),
        mk("Up", on_speed_up),
        mk("Down", on_speed_down),
        mk("Ctrl++", on_zoom_in),
        mk("Ctrl+=", on_zoom_in),
        mk("Ctrl+-", on_zoom_out),
        mk("M", on_add_marker),
        mk("L", on_toggle_loop),
    ]
    return shortcuts
