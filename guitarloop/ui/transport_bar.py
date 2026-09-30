"""Kontrol transport: play/pause/stop, seek, speed slider, volume, time label."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from guitarloop.core.engine import PlayerState
from guitarloop.utils.i18n import t
from guitarloop.utils.timefmt import format_ms


class TransportBar(QWidget):
    """Baris kontrol playback horizontal."""

    play_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    seek_back_clicked = Signal()
    seek_fwd_clicked = Signal()
    speed_changed = Signal(float)  # 0.25 .. 2.0
    volume_changed = Signal(float)  # 0.0 .. 1.0
    seek_slider_changed = Signal(int)  # ms (absolute)

    _SPEED_MIN = 25  # 0.25
    _SPEED_MAX = 200  # 2.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._playing = False
        self._duration_ms = 0
        self._position_ms = 0
        self._slider_seeking = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self.btn_back = QPushButton(t("btn_seek_back"), self)
        self.btn_play = QPushButton(t("btn_play"), self)
        self.btn_stop = QPushButton(t("btn_stop"), self)
        self.btn_fwd = QPushButton(t("btn_seek_fwd"), self)

        for w in (self.btn_back, self.btn_play, self.btn_stop, self.btn_fwd):
            w.setMinimumHeight(32)

        self.lbl_time = QLabel(t("not_loaded"), self)
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_time.setMinimumWidth(220)
        font = self.lbl_time.font()
        font.setStyleHint(font.StyleHint.Monospace)
        self.lbl_time.setFont(font)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setMinimumWidth(300)

        self.lbl_speed = QLabel(t("lbl_speed"), self)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.speed_slider.setRange(self._SPEED_MIN, self._SPEED_MAX)
        self.speed_slider.setValue(100)
        self.speed_slider.setMinimumWidth(140)
        self.lbl_speed_value = QLabel("100 %", self)
        self.lbl_speed_value.setMinimumWidth(56)
        self.lbl_speed_value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_vol = QLabel(t("lbl_volume"), self)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setMinimumWidth(100)

        layout.addWidget(self.btn_back)
        layout.addWidget(self.btn_play)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_fwd)
        layout.addSpacing(8)
        layout.addWidget(self.lbl_time)
        layout.addWidget(self.seek_slider, 1)
        layout.addSpacing(12)
        layout.addWidget(self.lbl_speed)
        layout.addWidget(self.speed_slider)
        layout.addWidget(self.lbl_speed_value)
        layout.addSpacing(12)
        layout.addWidget(self.lbl_vol)
        layout.addWidget(self.vol_slider)

        # ---- signal wiring ----
        self.btn_play.clicked.connect(self._on_play_click)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_back.clicked.connect(self.seek_back_clicked.emit)
        self.btn_fwd.clicked.connect(self.seek_fwd_clicked.emit)
        self.speed_slider.valueChanged.connect(self._on_speed_slider)
        self.vol_slider.valueChanged.connect(self._on_vol_slider)

        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderReleased.connect(self._on_slider_released)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)

        self._update_play_label()

    # ------------------------------------------------------------------
    # Slot internal
    # ------------------------------------------------------------------
    def _on_play_click(self) -> None:
        if self._playing:
            self.pause_clicked.emit()
        else:
            self.play_clicked.emit()

    def _on_speed_slider(self, value: int) -> None:
        pct = max(self._SPEED_MIN, min(self._SPEED_MAX, value))
        self.lbl_speed_value.setText(f"{pct} %")
        self.speed_changed.emit(pct / 100.0)

    def _on_vol_slider(self, value: int) -> None:
        self.volume_changed.emit(max(0, min(100, value)) / 100.0)

    def _on_slider_pressed(self) -> None:
        self._slider_seeking = True

    def _on_slider_released(self) -> None:
        self._slider_seeking = False
        self.seek_slider_changed.emit(self.seek_slider.value())

    def _on_slider_moved(self, _value: int) -> None:
        # Update label waktu real-time saat user drag slider
        self._update_time_label(self._slider_seeking, self.seek_slider.value())

    # ------------------------------------------------------------------
    # Public API (dipanggil dari MainWindow)
    # ------------------------------------------------------------------
    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.seek_slider.setRange(0, self._duration_ms)
        self._update_time_label(False, self._position_ms)

    def set_position(self, position_ms: int, *, from_user: bool = False) -> None:
        ms = max(0, int(position_ms))
        self._position_ms = ms
        if not self._slider_seeking or from_user:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(ms)
            self.seek_slider.blockSignals(False)
        if not from_user:
            self._update_time_label(self._slider_seeking, self.seek_slider.value())

    def set_speed(self, speed: float) -> None:
        pct = int(round(max(0.25, min(2.0, float(speed))) * 100))
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(pct)
        self.speed_slider.blockSignals(False)
        self.lbl_speed_value.setText(f"{pct} %")

    def set_volume(self, volume: float) -> None:
        v = int(round(max(0.0, min(1.0, float(volume))) * 100))
        self.vol_slider.blockSignals(True)
        self.vol_slider.setValue(v)
        self.vol_slider.blockSignals(False)

    def set_state(self, state: PlayerState) -> None:
        self._playing = state == PlayerState.PLAYING
        # Enable/disable kontrol sesuai state
        any_loaded = state in (PlayerState.LOADED, PlayerState.PLAYING, PlayerState.PAUSED)
        for w in (
            self.btn_back,
            self.btn_play,
            self.btn_stop,
            self.btn_fwd,
            self.seek_slider,
            self.speed_slider,
        ):
            w.setEnabled(any_loaded or state == PlayerState.PAUSED)
        self._update_play_label()

    # ------------------------------------------------------------------
    # Bantuan
    # ------------------------------------------------------------------
    def _update_play_label(self) -> None:
        self.btn_play.setText(t("btn_pause") if self._playing else t("btn_play"))

    def _update_time_label(self, user_dragging: bool, slider_ms: int) -> None:
        if self._duration_ms <= 0:
            self.lbl_time.setText(t("not_loaded"))
            return
        pos_ms = slider_ms if user_dragging else self._position_ms
        pos_str = format_ms(pos_ms, show_hours=self._duration_ms >= 3600_000)
        dur_str = format_ms(self._duration_ms, show_hours=self._duration_ms >= 3600_000)
        self.lbl_time.setText(t("time_format", pos=pos_str, dur=dur_str))
