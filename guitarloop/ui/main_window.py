"""Jendela utama aplikasi V0.5 (Markers & Loop Controller)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from guitarloop import __version__
from guitarloop.core.audio_import import (
    AudioImporter,
    ImportProgress,
    ImportResult,
    check_ffmpeg_available,
)
from guitarloop.core.engine import PlayerEngine, PlayerState
from guitarloop.core.loop_controller import (
    LoopAfterAction,
    LoopController,
    LoopMode,
)
from guitarloop.core.markers import MarkerCollection
from guitarloop.core.storage import Storage
from guitarloop.ui.loop_panel import LoopPanel
from guitarloop.ui.marker_list import MarkerList
from guitarloop.ui.qt_bridge import QtEngineBridge
from guitarloop.ui.shortcuts import register_shortcuts
from guitarloop.ui.transport_bar import TransportBar
from guitarloop.ui.waveform_widget import WaveformWidget
from guitarloop.utils.i18n import t
from guitarloop.utils.paths import ensure_dirs
from guitarloop.utils.timefmt import format_ms


def _fmt_time(ms: int) -> str:
    return format_ms(ms, show_hours=False)


_MODE_TEXT: dict[LoopMode, str] = {
    LoopMode.OFF: "Mati",
    LoopMode.A_B: "A → B",
    LoopMode.BAGIAN: "Bagian (Mn → Mn+1)",
    LoopMode.AWAL_MARKER: "Awal → Penanda",
    LoopMode.MARKER_AKHIR: "Penanda → Akhir",
}


# ---------------------------------------------------------------------------
# Worker thread untuk impor (agar UI tidak macet)
# ---------------------------------------------------------------------------
class _ImportWorker(QObject):
    progress = Signal(object)  # ImportProgress
    finished = Signal(object)  # ImportResult | Exception
    _cancel = False

    def __init__(self, importer: AudioImporter, source: Path) -> None:
        super().__init__()
        self._importer = importer
        self._source = source

    def run(self) -> None:
        def _cb(p: ImportProgress) -> None:
            if self._cancel:
                raise RuntimeError("import dibatalkan")
            self.progress.emit(p)

        try:
            result = self._importer.import_file(self._source, progress=_cb)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(exc)

    def cancel(self) -> None:
        self._cancel = True


class MainWindow(QMainWindow):
    """Jendela utama GuitarLoop Klasik V0.5 (markers + loop)."""

    _SEEK_STEP_MS = 5_000
    _SPEED_STEP = 0.05
    _POLL_INTERVAL_MS = 33
    _ZOOM_STEP = 1.25
    _SAVE_DEBOUNCE_SEC = 0.5  # PRD §6.5

    def __init__(
        self,
        *,
        engine: PlayerEngine,
        storage: Storage,
        importer: AudioImporter,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._storage = storage
        self._importer = importer

        self._markers = MarkerCollection()
        self._loop_ctrl: LoopController | None = None
        self._current_track_id: int | None = None
        self._current_audio_hash: str | None = None
        self._selected_marker_id: str = ""

        self._save_lock = threading.Lock()
        self._save_timer: threading.Timer | None = None

        self._import_thread: QThread | None = None
        self._import_worker: _ImportWorker | None = None

        ensure_dirs()
        self._bridge = QtEngineBridge(self)
        self._engine.add_listener(self._bridge)
        self._loop_ctrl = LoopController(self._engine, self._markers)
        self._engine.add_listener(self._loop_ctrl)

        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._register_shortcuts()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()
        self._engine.set_volume(self._transport.vol_slider.value() / 100.0)

    # --------------------------------------------------------------
    # UI construction
    # --------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle(t("app_title"))
        # Ukuran default SETENGAH dari 1280x720 → 640x360, UKURAN TETAP (fixed size).
        self.setFixedSize(1800, 720)
        self.setDockNestingEnabled(False)

        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._title_label = QLabel(" ", self)
        font = self._title_label.font()
        font.setPointSize(max(10, font.pointSize()))
        font.setBold(True)
        self._title_label.setFont(font)
        self._title_label.setContentsMargins(12, 8, 12, 4)

        self._waveform = WaveformWidget(self)
        self._transport = TransportBar(self)
        root.addWidget(self._title_label)
        root.addWidget(self._waveform, 1)
        root.addWidget(self._transport)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("")
        # ---- Status Bar Counter Loop PERMANEN (kanan bawah SELALU TERLIHAT) ----
        self._loop_status_permanent = QLabel(" 🔁 Loop: idle ", self)
        lsf = self._loop_status_permanent.font()
        lsf.setBold(True)
        lsf.setPointSize(10)
        self._loop_status_permanent.setFont(lsf)
        self._loop_status_permanent.setStyleSheet(
            "padding: 2px 10px 2px 10px;"
            "background-color: #2a2a2e; color: #999;"
            "border-radius: 3px; margin-right: 4px;"
        )
        self.statusBar().addPermanentWidget(self._loop_status_permanent)

        # Dock kiri: Loop
        self._loop_panel = LoopPanel(self)
        self._dock_loop = QDockWidget(t("dock_loop_title", default="Kontrol Loop"), self)
        self._dock_loop.setWidget(self._loop_panel)
        self._dock_loop.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._dock_loop)

        # Dock kanan: Markers
        self._marker_panel = MarkerList(self)
        self._dock_markers = QDockWidget(t("dock_markers_title", default="Daftar Penanda"), self)
        self._dock_markers.setWidget(self._marker_panel)
        self._dock_markers.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock_markers)

    def _build_menu(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu(t("menu_file"))
        act_open = QAction(t("action_open"), self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._on_open_file)
        m_file.addAction(act_open)
        m_file.addSeparator()
        act_quit = QAction(t("action_quit"), self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_view = mb.addMenu(t("menu_view"))
        act_zi = QAction(t("action_zoom_in"), self)
        act_zi.setShortcut("Ctrl++")
        act_zi.triggered.connect(lambda: self._waveform.zoom_by(self._ZOOM_STEP))
        m_view.addAction(act_zi)
        act_zo = QAction(t("action_zoom_out"), self)
        act_zo.setShortcut("Ctrl+-")
        act_zo.triggered.connect(lambda: self._waveform.zoom_by(1 / self._ZOOM_STEP))
        m_view.addAction(act_zo)

        m_help = mb.addMenu(t("menu_help"))
        act_about = QAction(t("action_about"), self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

    def _connect_signals(self) -> None:
        assert self._loop_ctrl is not None
        # Transport
        self._transport.play_clicked.connect(self._engine.play)
        self._transport.pause_clicked.connect(self._engine.pause)
        self._transport.stop_clicked.connect(self._on_transport_stop_clicked)
        self._transport.seek_back_clicked.connect(lambda: self._seek_relative(-self._SEEK_STEP_MS))
        self._transport.seek_fwd_clicked.connect(lambda: self._seek_relative(+self._SEEK_STEP_MS))
        self._transport.speed_changed.connect(self._on_speed_changed)
        self._transport.volume_changed.connect(self._on_volume_changed)
        self._transport.seek_slider_changed.connect(self._on_seek_user)

        # Waveform
        self._waveform.seek_requested.connect(self._on_seek_user)
        self._waveform.marker_add_requested.connect(self._on_add_marker_at)
        self._waveform.marker_selected_changed.connect(self._on_select_marker)
        self._waveform.marker_drag_moved.connect(self._on_marker_drag_preview)
        self._waveform.marker_dragged.connect(self._on_marker_moved)

        # Marker panel
        self._marker_panel.add_clicked.connect(
            lambda: self._on_add_marker_at(self._engine.position_ms)
        )
        self._marker_panel.remove_clicked.connect(self._on_remove_marker)
        self._marker_panel.rename_requested.connect(self._on_rename_marker)
        self._marker_panel.item_clicked.connect(self._on_list_marker_clicked)

        # Loop panel
        self._loop_panel.enabled_toggled.connect(self._on_loop_enable_toggled)
        self._loop_panel.mode_changed.connect(self._on_loop_mode_changed)
        self._loop_panel.ab_marker_changed.connect(self._on_loop_ab_marker_changed)
        self._loop_panel.marker_index_changed.connect(self._on_loop_marker_index_changed)
        self._loop_panel.repeat_changed.connect(self._on_loop_repeat_changed)
        self._loop_panel.after_action_changed.connect(self._on_loop_after_changed)

        # Engine bridge
        self._bridge.position_changed.connect(self._transport.set_position)
        self._bridge.position_changed.connect(self._waveform.set_position)
        self._bridge.position_changed.connect(self._on_position_tick)
        self._bridge.state_changed.connect(self._transport.set_state)
        self._bridge.state_changed.connect(self._on_engine_state)
        self._bridge.error.connect(self._on_engine_error)
        self._bridge.loop_iteration.connect(self._on_loop_iteration)
        self._bridge.finished.connect(
            lambda: self.statusBar().showMessage("Playback selesai.", 3000)
        )

    def _register_shortcuts(self) -> None:
        assert self._loop_ctrl is not None
        self._shortcuts = register_shortcuts(
            self,
            on_play_pause=self._on_toggle_play_pause,
            on_stop=self._engine.stop,
            on_seek_back=lambda: self._seek_relative(-self._SEEK_STEP_MS),
            on_seek_fwd=lambda: self._seek_relative(+self._SEEK_STEP_MS),
            on_speed_up=lambda: self._transport.set_speed(self._engine.speed + self._SPEED_STEP),
            on_speed_down=lambda: self._transport.set_speed(self._engine.speed - self._SPEED_STEP),
            on_open_file=self._on_open_file,
            on_zoom_in=lambda: self._waveform.zoom_by(self._ZOOM_STEP),
            on_zoom_out=lambda: self._waveform.zoom_by(1 / self._ZOOM_STEP),
            on_add_marker=lambda: self._on_add_marker_at(self._engine.position_ms),
            on_toggle_loop=self._on_toggle_loop,
            on_set_loop_a=self._on_set_loop_a_here,
            on_set_loop_b=self._on_set_loop_b_here,
            on_delete_marker=lambda: self._on_remove_marker(self._selected_marker_id),
            on_rename_marker=self._prompt_rename_selected,
            on_nudge_marker_left_1ms=lambda: self._nudge_selected(-1),
            on_nudge_marker_right_1ms=lambda: self._nudge_selected(+1),
            on_nudge_marker_left_10ms=lambda: self._nudge_selected(-10),
            on_nudge_marker_right_10ms=lambda: self._nudge_selected(+10),
            on_nudge_marker_left_100ms=lambda: self._nudge_selected(-100),
            on_nudge_marker_right_100ms=lambda: self._nudge_selected(+100),
        )

    # --------------------------------------------------------------
    # Polling & engine state
    # --------------------------------------------------------------
    def _on_poll(self) -> None:
        self._engine.poll()
        pos = self._engine.position_ms
        if self._loop_ctrl is not None:
            self._loop_ctrl.tick(pos)
        # ---- SOFTWARE LOOP FALLBACK 100% (native ab-loop dimatikan) ----
        bounds = self._engine.software_loop_bounds_ms()
        if bounds is None or self._loop_ctrl is None:
            self._update_loop_status_label()  # refresh realtime (bahkan tanpa loop)
            return
        a_ms, b_ms = bounds
        ctrl = self._loop_ctrl
        # Hanya proses jika posisi sudah DI DALAM range A..B+infinite (pos >= a_ms)
        # Jika user seek sebelum A, biarkan tidak usah seek balik.
        if ctrl.active and pos >= a_ms and pos >= b_ms + 4:
            # ⚠️ POSISI MELEWATI BATAS AKHIR (B) → WRAP ke AWAL (A).
            # Kita lakukan 5 aksi sekuensial:
            #  1. ENGINE.SEEK ke titik A (audio lompat realtime)
            #  2. Panggil ctrl.force_wrap_occurred() → NAIKKAN COUNTER LOOP (1 per wrap)
            #  3. Set ctrl._last_position = a_ms → bersihkan state tick berikutnya
            #  4. REFRESH UI LABEL STATUS secara PAKSA (agar counter TERLIHAT di panel)
            #  5. Print debug stderr untuk verifikasi
            self._engine.seek(a_ms)
            try:
                ctrl.force_wrap_occurred()
            except Exception as _e_wrap:
                print(
                    f"[LOOP-CTRL] force_wrap error (abaikan): {_e_wrap}",
                    file=sys.stderr,
                    flush=True,
                )
            # Pastikan internal state last_position LoopController sinkron
            try:
                ctrl._last_position = int(a_ms)
            except Exception:
                pass
            # ⚡ PAKSA REFRESH UI LABEL (tanpa menunggu sinyal bridge)
            self._update_loop_status_label()
            self._update_loop_area_visual()
            n = ctrl.iteration_done
            tot = ctrl.total_expected()
            tot_s = "∞" if tot is None else str(tot)
            print(
                f"[SOFTWARE-LOOP] 🔁 #{n}/{tot_s} OK: B({pos}ms) → A({a_ms}ms)",
                file=sys.stderr,
                flush=True,
            )
        # ---- UPDATE LABEL TIAP POLL TANPA WRAP PUN (realtime counter) ----
        self._update_loop_status_label()

    def _on_engine_state(self, state: object) -> None:
        if not isinstance(state, PlayerState):
            return
        if state in (PlayerState.LOADED, PlayerState.PLAYING, PlayerState.PAUSED):
            dur = self._engine.duration_ms
            if dur > 0:
                self._transport.set_duration(dur)
                if self._loop_ctrl is not None:
                    self._loop_ctrl.set_duration_ms(dur)

    def _on_engine_error(self, message: str) -> None:
        QMessageBox.critical(self, t("import_error_title"), str(message))

    def _on_transport_stop_clicked(self) -> None:
        self._engine.stop()
        if self._loop_ctrl is not None:
            self._loop_ctrl.reset_iteration_counter()
            self._update_loop_status_label()

    # --------------------------------------------------------------
    # Playback / seek / toggle play-pause
    # --------------------------------------------------------------
    def _on_toggle_play_pause(self) -> None:
        state = self._engine.state
        if state == PlayerState.PLAYING:
            self._engine.pause()
        elif state in (PlayerState.PAUSED, PlayerState.LOADED):
            self._engine.play()

    def _seek_relative(self, delta_ms: int) -> None:
        target = max(0, self._engine.position_ms + int(delta_ms))
        self._engine.seek(target)
        self._transport.set_position(target, from_user=True)
        self._waveform.set_position(target)

    def _on_seek_user(self, position_ms: int) -> None:
        self._engine.seek(int(position_ms))
        self._transport.set_position(position_ms, from_user=True)
        self._waveform.set_position(position_ms)

    def _on_speed_changed(self, speed: float) -> None:
        self._engine.set_speed(speed)
        self._persist_settings()

    def _on_volume_changed(self, volume: float) -> None:
        self._engine.set_volume(volume)
        self._persist_settings()

    def _on_position_tick(self, _pos_ms: int) -> None:
        if self._loop_ctrl is None:
            return
        if not self._loop_ctrl.config.is_infinite():
            expected_total = self._loop_ctrl.total_expected()
            if expected_total is not None:
                cur = min(self._loop_ctrl.iteration_done, expected_total)
                self._loop_panel.set_iteration_status(cur, expected_total)

    # --------------------------------------------------------------
    # Persistensi (debounced markers + settings)
    # --------------------------------------------------------------
    def _schedule_markers_save(self) -> None:
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(self._SAVE_DEBOUNCE_SEC, self._flush_markers_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _flush_markers_save(self) -> None:
        with self._save_lock:
            self._save_timer = None
        if self._current_track_id is None:
            return
        try:
            self._storage.save_markers(self._current_track_id, list(self._markers.all))
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Gagal simpan penanda: {exc}", 5000)

    def _persist_settings(self) -> None:
        if self._current_track_id is None:
            return
        lc = self._loop_ctrl
        mode_str: str | None = None
        a_ms: int | None = None
        b_ms: int | None = None
        repeat_count = 5
        after_str = "stop"
        if lc is not None:
            mode_str = None if lc.config.mode == LoopMode.OFF else lc.config.mode.value
            bounds = lc.resolve_bounds_ms()
            if bounds is not None:
                a_ms, b_ms = bounds
            repeat_count = 0 if lc.config.is_infinite() else lc.config.repeat_count
            after_str = lc.config.after.value
        try:
            self._storage.save_track_settings(
                track_id=self._current_track_id,
                speed=self._engine.speed,
                volume=self._engine.volume,
                loop_mode=mode_str,
                loop_a=a_ms,
                loop_b=b_ms,
                loop_after=after_str,
                repeat_count=repeat_count,
            )
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Gagal simpan pengaturan: {exc}", 5000)

    # --------------------------------------------------------------
    # Markers CRUD
    # --------------------------------------------------------------
    def _on_add_marker_at(self, time_ms: int) -> None:
        if self._current_track_id is None:
            self.statusBar().showMessage("Buka file audio terlebih dahulu.", 2000)
            return
        marker = self._markers.add(int(time_ms))
        if marker is None:
            self.statusBar().showMessage(
                f"Penanda terlalu dekat (jarak < {self._markers.min_gap_ms} ms minimum)", 3000
            )
            return
        self._selected_marker_id = marker.id
        self._sync_marker_widgets_all()
        self._schedule_markers_save()
        self.statusBar().showMessage(f"Penanda ditambah: {marker.label}", 1500)

    def _on_remove_marker(self, marker_id: str) -> None:
        if not marker_id:
            return
        if self._markers.remove(marker_id):
            if self._selected_marker_id == marker_id:
                self._selected_marker_id = ""
            self._sync_marker_widgets_all()
            self._schedule_markers_save()
            self._reapply_loop_controller_bounds()
            self._persist_settings()

    def _on_rename_marker(self, marker_id: str, new_label: str) -> None:
        if self._markers.rename(marker_id, new_label):
            self._sync_marker_widgets_all(keep_selection=True)
            self._schedule_markers_save()

    def _prompt_rename_selected(self) -> None:
        mid = self._selected_marker_id
        if not mid:
            self.statusBar().showMessage("Pilih penanda terlebih dahulu.", 2000)
            return
        marker = self._markers.get(mid)
        if marker is None:
            return
        new_label, ok = QInputDialog.getText(
            self,
            t("rename_dlg_title", default="Ganti Nama Penanda"),
            t("rename_dlg_prompt", default="Label penanda:"),
            QLineEdit.EchoMode.Normal,
            marker.label,
        )
        if ok and new_label is not None:
            self._on_rename_marker(mid, new_label)

    def _on_select_marker(self, marker_id: str) -> None:
        self._selected_marker_id = marker_id or ""
        self._waveform.set_selected_marker(self._selected_marker_id)
        self._marker_panel.update_markers(self._markers, selected_id=self._selected_marker_id)

    def _on_list_marker_clicked(self, marker_id: str) -> None:
        marker = self._markers.get(marker_id)
        if marker is None:
            return
        self._selected_marker_id = marker_id
        self._waveform.set_selected_marker(marker_id)
        self._marker_panel.update_markers(self._markers, selected_id=marker_id)
        self._on_seek_user(marker.time_ms)

    def _on_marker_drag_preview(self, _marker_id: str, _new_ms: int) -> None:
        return  # Biarkan visual di waveform preview dulu; final check di release

    def _on_marker_moved(self, marker_id: str, new_ms: int) -> None:
        if not marker_id:
            return
        ok = self._markers.move(marker_id, int(new_ms), enforce_gap=True)
        if not ok:
            self._sync_marker_widgets_all(keep_selection=True)
            self.statusBar().showMessage(
                f"Penanda tidak bisa ditempatkan (jarak < {self._markers.min_gap_ms} ms)", 2500
            )
            return
        self._sync_marker_widgets_all(keep_selection=True)
        self._schedule_markers_save()
        self._reapply_loop_controller_bounds()
        self._persist_settings()

    def _nudge_selected(self, delta_ms: int) -> None:
        mid = self._selected_marker_id
        if not mid:
            self._seek_relative(int(delta_ms))
            return
        if self._markers.nudge(mid, int(delta_ms)):
            self._sync_marker_widgets_all(keep_selection=True)
            self._schedule_markers_save()
            self._reapply_loop_controller_bounds()
            self._persist_settings()

    def _sync_marker_widgets_all(self, *, keep_selection: bool = True) -> None:
        sel = self._selected_marker_id if keep_selection else ""
        self._waveform.set_markers(self._markers)
        self._marker_panel.update_markers(self._markers, selected_id=sel)
        self._waveform.set_selected_marker(sel)
        self._loop_panel.update_markers(list(self._markers))

    # --------------------------------------------------------------
    # Loop controller
    # --------------------------------------------------------------
    def _on_loop_enable_toggled(self, checked: bool) -> None:
        if self._loop_ctrl is None:
            return
        self._loop_ctrl.set_enabled(bool(checked))
        mode = self._loop_ctrl.config.mode
        # Sync mode di UI (jika user check enable tapi mode OFF → auto pilih BAGIAN)
        self._loop_panel.set_mode(mode)
        self._update_loop_area_visual()
        self._update_loop_status_label()
        self._persist_settings()
        msg = "✅ Loop AKTIF. " if self._loop_ctrl.active else "⏸️ Loop dimatikan."
        if self._loop_ctrl.active:
            bounds = self._loop_ctrl.resolve_bounds_ms()
            if bounds:
                from guitarloop.utils.timefmt import format_ms

                a, b = bounds
                msg += f"Rentang: {format_ms(a)} → {format_ms(b)}"
        self.statusBar().showMessage(msg, 3500)

    def _on_toggle_loop(self) -> None:
        if self._loop_ctrl is None:
            return
        self._loop_ctrl.toggle()
        mode = self._loop_ctrl.config.mode
        self._loop_panel.set_mode(mode)
        self._update_loop_area_visual()
        self._update_loop_status_label()
        self._persist_settings()
        msg = (
            "Loop dimatikan."
            if mode == LoopMode.OFF
            else f"Loop aktif: {_MODE_TEXT.get(mode, mode.value)}"
        )
        self.statusBar().showMessage(msg, 1800)

    def _on_set_loop_a_here(self) -> None:
        if self._loop_ctrl is None:
            return
        a_ms = self._engine.position_ms
        b_ms = self._loop_ctrl.config.loop_b_ms
        if b_ms is not None and int(b_ms) > int(a_ms) + 8:
            self._loop_ctrl.set_ab_ms(int(a_ms), int(b_ms))
            self._sync_loop_mode_to_ui()
            self._update_loop_area_visual()
            self._persist_settings()
            self.statusBar().showMessage(f"A-B diset: {_fmt_time(a_ms)} → {_fmt_time(b_ms)}", 2200)
        else:
            self._loop_ctrl.config.loop_a_ms = int(a_ms)
            self.statusBar().showMessage(f"Titik A diset: {_fmt_time(a_ms)}", 1800)

    def _on_set_loop_b_here(self) -> None:
        if self._loop_ctrl is None:
            return
        b_ms = self._engine.position_ms
        a_ms = self._loop_ctrl.config.loop_a_ms
        if a_ms is not None and int(b_ms) > int(a_ms) + 8:
            self._loop_ctrl.set_ab_ms(int(a_ms), int(b_ms))
            self._sync_loop_mode_to_ui()
            self._update_loop_area_visual()
            self._persist_settings()
            self.statusBar().showMessage(f"A-B diset: {_fmt_time(a_ms)} → {_fmt_time(b_ms)}", 2200)
        else:
            self._loop_ctrl.config.loop_b_ms = int(b_ms)
            self.statusBar().showMessage(f"Titik B diset: {_fmt_time(b_ms)}", 1800)

    def _on_loop_mode_changed(self, mode_obj: object) -> None:
        if self._loop_ctrl is None or not isinstance(mode_obj, LoopMode):
            return
        self._loop_ctrl.set_mode(mode_obj)
        self._update_loop_area_visual()
        self._update_loop_status_label()
        self._persist_settings()

    def _on_loop_ab_marker_changed(self, id_a: str, id_b: str) -> None:
        if self._loop_ctrl is None:
            return
        if self._loop_ctrl.set_ab_markers(id_a, id_b):
            self._update_loop_area_visual()
            self._update_loop_status_label()
            self._persist_settings()

    def _on_loop_marker_index_changed(self, idx: int) -> None:
        if self._loop_ctrl is None:
            return
        mode = self._loop_ctrl.config.mode
        if mode == LoopMode.BAGIAN:
            self._loop_ctrl.set_bagian(idx)
        elif mode == LoopMode.AWAL_MARKER:
            self._loop_ctrl.set_awal_ke_marker(idx)
        elif mode == LoopMode.MARKER_AKHIR:
            self._loop_ctrl.set_marker_ke_akhir(idx)
        self._loop_panel.set_selected_marker_index(idx)
        self._update_loop_area_visual()
        self._update_loop_status_label()
        self._persist_settings()

    def _on_loop_repeat_changed(self, count: int) -> None:
        if self._loop_ctrl is None:
            return
        self._loop_ctrl.set_repeat_count(int(count))
        self._update_loop_status_label()
        self._persist_settings()

    def _on_loop_after_changed(self, action_obj: object) -> None:
        if self._loop_ctrl is None or not isinstance(action_obj, LoopAfterAction):
            return
        self._loop_ctrl.set_after_action(action_obj)
        self._persist_settings()

    def _reapply_loop_controller_bounds(self) -> None:
        if self._loop_ctrl is None:
            return
        lc = self._loop_ctrl
        mode = lc.config.mode
        if mode == LoopMode.A_B and lc.config.marker_a_id and lc.config.marker_b_id:
            lc.set_ab_markers(lc.config.marker_a_id, lc.config.marker_b_id)
        elif mode == LoopMode.BAGIAN:
            lc.set_bagian(lc.config.marker_index)
        elif mode == LoopMode.AWAL_MARKER:
            lc.set_awal_ke_marker(lc.config.marker_index)
        elif mode == LoopMode.MARKER_AKHIR:
            lc.set_marker_ke_akhir(lc.config.marker_index)
        self._update_loop_area_visual()
        self._update_loop_status_label()

    def _update_loop_area_visual(self) -> None:
        if self._loop_ctrl is None:
            self._waveform.set_loop(None, None)
            return
        bounds = self._loop_ctrl.resolve_bounds_ms()
        self._waveform.set_loop(bounds[0] if bounds else None, bounds[1] if bounds else None)

    def _update_loop_status_label(self) -> None:
        if self._loop_ctrl is None:
            self._loop_panel.set_iteration_status(0, 0)
            try:
                self._loop_status_permanent.setText("🔁 Loop: idle")
                self._loop_status_permanent.setStyleSheet(
                    "padding: 2px 10px 2px 10px;"
                    "background-color: #2a2a2e; color: #999;"
                    "border-radius: 3px; margin-right: 4px;"
                )
            except Exception:
                pass
            return
        cur = self._loop_ctrl.iteration_done
        tot = self._loop_ctrl.total_expected()
        self._loop_panel.set_iteration_status(cur, tot)
        # ----- UPDATE StatusBar permanen counter ----- 
        try:
            if tot is None:
                txt = f"🔁 ∞ Loop ke-{cur}"
                color_bg, color_fg = "#2C3E50", "#3498DB"
            elif tot <= 0:
                txt = "🔁 Loop: idle"
                color_bg, color_fg = "#2a2a2e", "#999999"
            elif cur >= tot:
                txt = f"🔁 SELESAI {tot}x ulangan ✅"
                color_bg, color_fg = "#143A23", "#2ECC71"
            else:
                sisa = max(0, tot - cur)
                txt = f"🔁 Loop: {cur}/{tot}  (sisa {sisa})"
                color_bg, color_fg = "#3A1514", "#FF5E5E"
            self._loop_status_permanent.setText(txt)
            self._loop_status_permanent.setStyleSheet(
                f"padding: 2px 10px 2px 10px; margin-right: 4px;"
                f"background-color: {color_bg}; color: {color_fg};"
                "border-radius: 3px; font-weight: 700;"
            )
            # Tampilkan juga di message (kiri bawah) sambil tanpa timpa status lain
            self.statusBar().showMessage(txt, 1500)
        except Exception:
            pass

    def _on_loop_iteration(self, _delta: int) -> None:
        self._update_loop_status_label()

    def _sync_loop_mode_to_ui(self) -> None:
        if self._loop_ctrl is None:
            return
        self._loop_panel.set_mode(self._loop_ctrl.config.mode)
        self._loop_panel.set_repeat(
            0 if self._loop_ctrl.config.is_infinite() else self._loop_ctrl.config.repeat_count
        )
        self._loop_panel.set_after_action(self._loop_ctrl.config.after)
        self._update_loop_status_label()

    # --------------------------------------------------------------
    # Impor file
    # --------------------------------------------------------------
    def _on_open_file(self) -> None:
        if not check_ffmpeg_available():
            QMessageBox.warning(self, t("ffmpeg_not_found_title"), t("ffmpeg_not_found_msg"))
            return
        path, _ = QFileDialog.getOpenFileName(
            self, t("open_dialog_title"), "", t("open_dialog_filter")
        )
        if not path:
            return
        self._start_import(Path(path))

    def _start_import(self, source: Path) -> None:
        if self._import_thread is not None:
            self.statusBar().showMessage("Impor lain sedang berjalan...", 2000)
            return
        self._waveform.set_loading(True)
        self.statusBar().showMessage(t("import_in_progress", name=source.name))

        self._import_thread = QThread(self)
        self._import_worker = _ImportWorker(self._importer, source)
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_done)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_thread.finished.connect(self._cleanup_import)
        self._import_thread.start()

    def _on_import_progress(self, prog: object) -> None:
        if not isinstance(prog, ImportProgress):
            return
        pct = int(max(0, min(1, prog.ratio)) * 100)
        msg = (
            f"[{pct:>3d}%] {prog.phase} — {prog.message}"
            if prog.message
            else f"[{pct:>3d}%] {prog.phase}"
        )
        self.statusBar().showMessage(msg)

    def _on_import_done(self, payload: object) -> None:
        self._waveform.set_loading(False)
        if isinstance(payload, Exception):
            reason = str(payload) or payload.__class__.__name__
            msg = t(
                "import_error_msg",
                path=getattr(self._import_worker, "_source", "?"),
                reason=reason,
            )
            self.statusBar().showMessage(t("import_error_title"), 5000)
            QMessageBox.critical(self, t("import_error_title"), msg)
            return
        if isinstance(payload, ImportResult):
            self._apply_import_result(payload)

    def _apply_import_result(self, res: ImportResult) -> None:
        # 1. Track DB
        self._current_track_id = self._storage.upsert_track(
            audio_hash=res.audio_hash,
            path=res.source_path,
            title=res.title,
            artist=res.artist,
            duration_ms=res.duration_ms,
        )
        self._current_audio_hash = res.audio_hash

        # 2. Load settings + markers dari DB (persistensi §6.5)
        settings = self._storage.load_track_settings(self._current_track_id)
        speed = float(settings.get("speed", 1.0))
        volume = float(settings.get("volume", 0.8))
        markers = self._storage.load_markers(self._current_track_id)
        self._markers.replace_all(markers)
        self._selected_marker_id = ""

        # 3. Load ke engine + transport
        self._engine.load(str(res.wav_path))
        self._transport.set_duration(res.duration_ms)
        self._transport.set_speed(speed)
        self._transport.set_volume(volume)
        self._engine.set_speed(speed)
        self._engine.set_volume(volume)
        if self._loop_ctrl is not None:
            self._loop_ctrl.set_duration_ms(res.duration_ms)

        # 4. Waveform
        self._waveform.set_peaks(res.peaks)
        self._sync_marker_widgets_all(keep_selection=False)

        # 5. Restore loop mode & pengaturan dari DB jika tersedia
        if self._loop_ctrl is not None:
            mode_val = settings.get("loop_mode") or "off"
            mode = LoopMode.OFF
            for m in LoopMode:
                if m.value == mode_val:
                    mode = m
                    break
            self._loop_ctrl.config.repeat_count = max(0, int(settings.get("repeat_count", 5)))
            after_val = settings.get("loop_after") or "stop"
            for a in LoopAfterAction:
                if a.value == after_val:
                    self._loop_ctrl.config.after = a
                    break
            self._loop_ctrl.set_mode(mode)
            # Mode A-B: coba restore dari loop_a/loop_b ms
            if mode == LoopMode.A_B:
                la = settings.get("loop_a")
                lb = settings.get("loop_b")
                if isinstance(la, int) and isinstance(lb, int) and lb > la + 8:
                    self._loop_ctrl.set_ab_ms(la, lb)
            self._sync_loop_mode_to_ui()
            self._update_loop_area_visual()

        # 6. Judul
        title_parts = [res.title]
        if res.artist:
            title_parts.append(f"— {res.artist}")
        self._title_label.setText(" ".join(title_parts))
        self.setWindowTitle(t("app_title_with_file", title=res.title))
        self.statusBar().showMessage(t("import_done", title=res.title), 4000)
        # Snapshot awal
        self._schedule_markers_save()
        self._persist_settings()

    def _cleanup_import(self) -> None:
        if self._import_worker is not None:
            try:
                self._import_worker.setParent(None)
            except Exception:  # noqa: BLE001
                pass
            self._import_worker.deleteLater()
            self._import_worker = None
        if self._import_thread is not None:
            self._import_thread.deleteLater()
            self._import_thread = None

    # --------------------------------------------------------------
    # Lainnya
    # --------------------------------------------------------------
    def _on_about(self) -> None:
        QMessageBox.information(self, t("about_title"), t("about_body", version=__version__))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # Flush segera semua save pending
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        try:
            self._storage.force_flush()
        except Exception:  # noqa: BLE001
            pass
        self._persist_settings()
        self._flush_markers_save()
        try:
            self._storage.force_flush()
        except Exception:  # noqa: BLE001
            pass
        self._poll_timer.stop()
        if self._import_thread is not None and self._import_worker is not None:
            self._import_worker.cancel()
        if self._loop_ctrl is not None:
            self._engine.remove_listener(self._loop_ctrl)
        self._engine.remove_listener(self._bridge)
        self._engine.unload()
        self._engine.shutdown()
        try:
            self._storage.force_flush()
        except Exception:  # noqa: BLE001
            pass
        self._storage.close()
        super().closeEvent(event)
