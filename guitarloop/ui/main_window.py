"""Jendela utama aplikasi."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
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
from guitarloop.core.storage import Storage
from guitarloop.ui.qt_bridge import QtEngineBridge
from guitarloop.ui.shortcuts import register_shortcuts
from guitarloop.ui.transport_bar import TransportBar
from guitarloop.ui.waveform_widget import WaveformWidget
from guitarloop.utils.i18n import t
from guitarloop.utils.paths import ensure_dirs


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
    """Jendela utama GuitarLoop Klasik V0.1."""

    # --- Konstan ---
    _SEEK_STEP_MS = 5_000
    _SPEED_STEP = 0.05
    _POLL_INTERVAL_MS = 33  # ~30 Hz
    _ZOOM_STEP = 1.25

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

        self._current_track_id: int | None = None
        self._current_audio_hash: str | None = None
        self._import_thread: QThread | None = None
        self._import_worker: _ImportWorker | None = None

        ensure_dirs()
        self._bridge = QtEngineBridge(self)
        self._engine.add_listener(self._bridge)

        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._register_shortcuts()

        # Polling position (lebih stabil dibanding observer native mpv)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()

        self._engine.set_volume(self._transport.vol_slider.value() / 100.0)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle(t("app_title"))
        self.resize(1100, 620)

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
        # Transport bar
        self._transport.play_clicked.connect(self._engine.play)
        self._transport.pause_clicked.connect(self._engine.pause)
        self._transport.stop_clicked.connect(self._engine.stop)
        self._transport.seek_back_clicked.connect(lambda: self._seek_relative(-self._SEEK_STEP_MS))
        self._transport.seek_fwd_clicked.connect(lambda: self._seek_relative(+self._SEEK_STEP_MS))
        self._transport.speed_changed.connect(self._on_speed_changed)
        self._transport.volume_changed.connect(self._on_volume_changed)
        self._transport.seek_slider_changed.connect(self._on_seek_user)

        # Waveform
        self._waveform.seek_requested.connect(self._on_seek_user)

        # Engine via bridge
        self._bridge.position_changed.connect(self._transport.set_position)
        self._bridge.position_changed.connect(self._waveform.set_position)
        self._bridge.state_changed.connect(self._transport.set_state)
        self._bridge.state_changed.connect(self._on_engine_state)
        self._bridge.error.connect(self._on_engine_error)
        self._bridge.finished.connect(
            lambda: self.statusBar().showMessage("Playback selesai.", 3000)
        )

    def _register_shortcuts(self) -> None:
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
            on_add_marker=lambda: self.statusBar().showMessage(
                "Fitur marker tersedia di V0.5.", 2000
            ),
            on_toggle_loop=lambda: self.statusBar().showMessage(
                "Fitur loop tersedia di V0.5.", 2000
            ),
        )

    # ------------------------------------------------------------------
    # Slots: playback control
    # ------------------------------------------------------------------
    def _on_toggle_play_pause(self) -> None:
        state = self._engine.state
        if state in (PlayerState.PLAYING,):
            self._engine.pause()
        elif state in (PlayerState.PAUSED, PlayerState.LOADED):
            self._engine.play()
        # IDLE: biarkan, tidak ada file.

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

    def _on_poll(self) -> None:
        # Poll juga memancarkan position_changed via listener engine.
        self._engine.poll()

    def _on_engine_state(self, state: object) -> None:
        if not isinstance(state, PlayerState):
            return
        if state in (PlayerState.LOADED, PlayerState.PLAYING, PlayerState.PAUSED):
            dur = self._engine.duration_ms
            if dur > 0:
                self._transport.set_duration(dur)

    def _on_engine_error(self, message: str) -> None:
        QMessageBox.critical(self, t("import_error_title"), str(message))

    # ------------------------------------------------------------------
    # Impor file
    # ------------------------------------------------------------------
    def _on_open_file(self) -> None:
        if not check_ffmpeg_available():
            QMessageBox.warning(self, t("ffmpeg_not_found_title"), t("ffmpeg_not_found_msg"))
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("open_dialog_title"),
            "",
            t("open_dialog_filter"),
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
        self.statusBar().showMessage(
            f"[{pct:>3d}%] {prog.phase} — {prog.message}"
            if prog.message
            else f"[{pct:>3d}%] {prog.phase}"
        )

    def _on_import_done(self, payload: object) -> None:
        self._waveform.set_loading(False)
        if isinstance(payload, Exception):
            # Munculkan error box (tidak fatal untuk app)
            reason = str(payload) or payload.__class__.__name__
            msg = t(
                "import_error_msg",
                path=getattr(self._import_worker, "_source", "?"),
                reason=reason,
            )
            self.statusBar().showMessage(t("import_error_title"), 5000)
            QMessageBox.critical(self, t("import_error_title"), msg)
            return
        if not isinstance(payload, ImportResult):
            return
        res: ImportResult = payload
        self._apply_import_result(res)

    def _apply_import_result(self, res: ImportResult) -> None:
        # 1. Simpan ke DB
        self._current_track_id = self._storage.upsert_track(
            audio_hash=res.audio_hash,
            path=res.source_path,
            title=res.title,
            artist=res.artist,
            duration_ms=res.duration_ms,
        )
        self._current_audio_hash = res.audio_hash

        # 2. Load pengaturan lama jika ada
        settings = self._storage.load_track_settings(self._current_track_id)
        speed = float(settings.get("speed", 1.0))
        volume = float(settings.get("volume", 0.8))

        # 3. Load ke engine
        self._engine.load(str(res.wav_path))
        # Tunggu state LOADED (bridge akan handle durasi; tapi kita juga set
        # dari import_result agar UI lebih responsif)
        self._transport.set_duration(res.duration_ms)
        self._transport.set_speed(speed)
        self._transport.set_volume(volume)
        self._engine.set_speed(speed)
        self._engine.set_volume(volume)

        # 4. Pasang waveform peaks
        self._waveform.set_peaks(res.peaks)

        # 5. Judul window
        title_parts = [res.title]
        if res.artist:
            title_parts.append(f"— {res.artist}")
        self._title_label.setText(" ".join(title_parts))
        self.setWindowTitle(t("app_title_with_file", title=res.title))
        self.statusBar().showMessage(t("import_done", title=res.title), 4000)

    def _cleanup_import(self) -> None:
        if self._import_worker is not None:
            self._import_worker.setParent(None)
            self._import_worker.deleteLater()
            self._import_worker = None
        if self._import_thread is not None:
            self._import_thread.deleteLater()
            self._import_thread = None

    def _persist_settings(self) -> None:
        if self._current_track_id is None:
            return
        self._storage.save_track_settings(
            track_id=self._current_track_id,
            speed=self._engine.speed,
            volume=self._engine.volume,
        )

    # ------------------------------------------------------------------
    # Lainnya
    # ------------------------------------------------------------------
    def _on_about(self) -> None:
        QMessageBox.information(
            self,
            t("about_title"),
            t("about_body", version=__version__),
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt naming)
        # Simpan setting terakhir sebelum tutup
        self._persist_settings()
        self._poll_timer.stop()
        if self._import_thread is not None and self._import_worker is not None:
            self._import_worker.cancel()
        self._engine.remove_listener(self._bridge)
        self._engine.unload()
        self._engine.shutdown()
        self._storage.close()
        super().closeEvent(event)
