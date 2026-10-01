"""Pendaftaran pintasan keyboard di QMainWindow (§7, PRD)."""

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
    # ---- V0.5 marker + loop ----
    on_add_marker: Callable[[], None],
    on_toggle_loop: Callable[[], None],
    on_set_loop_a: Callable[[], None],
    on_set_loop_b: Callable[[], None],
    on_delete_marker: Callable[[], None],
    on_rename_marker: Callable[[], None],
    on_nudge_marker_left_1ms: Callable[[], None],
    on_nudge_marker_right_1ms: Callable[[], None],
    on_nudge_marker_left_10ms: Callable[[], None],
    on_nudge_marker_right_10ms: Callable[[], None],
    on_nudge_marker_left_100ms: Callable[[], None],
    on_nudge_marker_right_100ms: Callable[[], None],
) -> list[QShortcut]:
    """Daftarkan pintasan keyboard dan return list-nya (untuk simpan reference)."""

    def mk(
        seq: str,
        cb: Callable[[], None],
        ctx: Qt.ShortcutContext = Qt.ShortcutContext.ApplicationShortcut,
    ) -> QShortcut:
        sc = QShortcut(QKeySequence(seq), window)
        sc.setContext(ctx)
        sc.activated.connect(cb)
        return sc

    shortcuts: list[QShortcut] = []

    # === Transport & umum (V0.1) ===
    shortcuts.append(mk("Space", on_play_pause))
    shortcuts.append(mk("Ctrl+S", on_stop))
    shortcuts.append(mk("Ctrl+O", on_open_file))
    shortcuts.append(mk("Left", on_seek_back))
    shortcuts.append(mk("Right", on_seek_fwd))
    shortcuts.append(mk("Up", on_speed_up))
    shortcuts.append(mk("Down", on_speed_down))
    shortcuts.append(mk("Ctrl++", on_zoom_in))
    shortcuts.append(mk("Ctrl+=", on_zoom_in))
    shortcuts.append(mk("Ctrl+-", on_zoom_out))

    # === Marker & Loop (V0.5, PRD §7) ===
    shortcuts.append(mk("M", on_add_marker))
    shortcuts.append(mk("L", on_toggle_loop))
    shortcuts.append(mk("[", on_set_loop_a))
    shortcuts.append(mk("]", on_set_loop_b))
    shortcuts.append(mk("Delete", on_delete_marker))
    shortcuts.append(mk("F2", on_rename_marker))

    # Nudge marker halus: Arrow dengan modifier
    # Ctrl + Arrow = ±1 ms
    shortcuts.append(mk("Ctrl+Left", on_nudge_marker_left_1ms))
    shortcuts.append(mk("Ctrl+Right", on_nudge_marker_right_1ms))
    # (Plain) Left/Right masih digunakan untuk seek (diatas). Jadi nudge 10 ms
    # default menggunakan Alt + Arrow (agar tidak tabrakan), namun shortcut
    # Shift + Arrow juga disediakan sebagai fallback untuk konsisten dengan
    # spesifikasi PRD "Shift ±100ms" dan "plain arrow ±10ms bisa nudge JIKA
    # marker terpilih". Penentuan "marker terpilih vs seek" diserahkan ke
    # handler di MainWindow dengan memanggil dua function terpisah via
    # window-level dispatcher.
    shortcuts.append(mk("Alt+Left", on_nudge_marker_left_10ms))
    shortcuts.append(mk("Alt+Right", on_nudge_marker_right_10ms))
    shortcuts.append(mk("Shift+Left", on_nudge_marker_left_100ms))
    shortcuts.append(mk("Shift+Right", on_nudge_marker_right_100ms))

    return shortcuts
