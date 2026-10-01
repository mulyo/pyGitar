"""Widget waveform kustom dengan QPainter.

Fitur V0.1:
- Render min/max peaks dari WaveformPeaks
- Playhead garis vertikal
- Klik = seek
- Zoom dengan Ctrl+Wheel / tombol + / -
- Scroll horizontal via seret atau scroll biasa
- Placeholder teks saat belum ada data
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from guitarloop.core.audio_import import WaveformPeaks
from guitarloop.core.markers import Marker
from guitarloop.utils.i18n import t

# Palet warna (tema terang default; bisa diganti V1.2)
_BG = QColor("#F5F3EF")
_CENTERLINE = QColor("#C8BFAC")
_WAVE = QColor("#3F7EA3")
_WAVE_OUTLINE = QColor("#2E5F7D")
_PLAYHEAD = QColor("#C43A31")
_LOOP_AREA = QColor(255, 236, 170, 110)
_TEXT = QColor("#5A4E3C")
_MARKER_HIT_PX = 6  # toleransi klik marker (pixel kiri/kanan garis)
_MARKER_LABEL_H = 18


class WaveformWidget(QWidget):
    """Widget waveform dengan zoom, playhead, markers, loop area."""

    seek_requested = Signal(int)  # ms posisi baru
    zoom_requested = Signal(float)  # faktor zoom (relatif)

    # Marker signals (V0.5)
    marker_add_requested = Signal(int)  # ms posisi user minta add (double click)
    marker_selected_changed = Signal(str)  # marker_id (atau "" jika none)
    marker_dragged = Signal(str, int)  # marker_id, new_time_ms (final drop)
    marker_drag_moved = Signal(str, int)  # marker_id, preview (opsional real-time)

    # Zoom: pixel per detik. min=10 (sangat perkecil), max=2000 (sangat detail)
    _MIN_PPS = 10
    _MAX_PPS = 2000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)  # tambah tinggi untuk label marker di atas
        self.setMouseTracking(True)
        self._peaks: WaveformPeaks | None = None
        self._duration_ms: int = 0
        self._position_ms: int = 0
        self._pps: float = 100.0  # pixels per second (zoom level)
        self._offset_ms: int = 0  # posisi paling kiri di viewport
        self._loading = False

        # Area loop
        self._loop_a_ms: int | None = None
        self._loop_b_ms: int | None = None

        # Markers
        self._markers: list[Marker] = []
        self._selected_marker_id: str = ""
        self._drag_marker_id: str | None = None
        self._drag_start_x_offset_px: float = 0.0  # jarak x cursor ke titik marker saat tekan
        self._label_font = QFont(self.font())
        self._label_font.setPointSize(max(8, self.font().pointSize() - 1))
        self._label_font.setBold(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_peaks(self, peaks: WaveformPeaks | None) -> None:
        self._peaks = peaks
        self._duration_ms = peaks.duration_ms if peaks is not None else 0
        self._offset_ms = 0
        self._position_ms = 0
        self.update()

    def set_loading(self, loading: bool) -> None:
        self._loading = loading
        self.update()

    def set_position(self, position_ms: int) -> None:
        ms = max(0, int(position_ms))
        self._position_ms = ms
        # Auto-scroll jika playhead keluar viewport
        if self._duration_ms > 0:
            viewport_ms = self._viewport_duration_ms()
            if ms < self._offset_ms or ms > self._offset_ms + viewport_ms:
                self._offset_ms = max(0, ms - viewport_ms // 4)
        self.update()

    def set_loop(self, a_ms: int | None, b_ms: int | None) -> None:
        self._loop_a_ms = a_ms
        self._loop_b_ms = b_ms
        self.update()

    # ------------------------------------------------------------------
    # Public API — Markers (V0.5)
    # ------------------------------------------------------------------
    def set_markers(self, markers: Iterable[Marker]) -> None:
        """Perbarui tampilan daftar marker dari collection."""
        self._markers = [Marker(m.id, int(m.time_ms), m.label, m.color, m.note) for m in markers]
        self.update()

    def set_selected_marker(self, marker_id: str) -> None:
        if marker_id != self._selected_marker_id:
            self._selected_marker_id = marker_id
            self.update()

    def _hit_marker(self, x_px: float) -> Marker | None:
        """Cari marker terdekat dalam _MARKER_HIT_PX pixel dari x_px."""
        best: Marker | None = None
        best_d: float = 1e12
        for m in self._markers:
            x = self._ms_to_x(m.time_ms)
            d = abs(x - x_px)
            if d <= _MARKER_HIT_PX and d < best_d:
                best = m
                best_d = d
        return best

    def set_zoom(self, pps: float) -> None:
        self._pps = max(self._MIN_PPS, min(self._MAX_PPS, float(pps)))
        self._clamp_offset()
        self.update()

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self._pps * float(factor))
        self.zoom_requested.emit(self._pps)

    # ------------------------------------------------------------------
    # Bantuan geometry
    # ------------------------------------------------------------------
    def _viewport_duration_ms(self) -> int:
        w = max(1, self.width())
        return max(1, int(round(w * 1000.0 / self._pps)))

    def _clamp_offset(self) -> None:
        if self._duration_ms <= 0:
            self._offset_ms = 0
            return
        vdur = self._viewport_duration_ms()
        max_off = max(0, self._duration_ms - vdur)
        self._offset_ms = max(0, min(self._offset_ms, max_off))

    def _ms_to_x(self, ms: int) -> float:
        return (ms - self._offset_ms) * self._pps / 1000.0

    def _x_to_ms(self, x: float) -> int:
        return max(0, min(self._duration_ms, int(round(self._offset_ms + x * 1000.0 / self._pps))))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect()

        # Background
        painter.fillRect(rect, _BG)

        if self._loading:
            painter.setPen(_TEXT)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, t("waveform_loading"))
            return
        if self._peaks is None or self._duration_ms <= 0:
            painter.setPen(_TEXT)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, t("waveform_empty"))
            return

        # Draw loop area di belakang waveform
        if self._loop_a_ms is not None and self._loop_b_ms is not None:
            a_x = self._ms_to_x(self._loop_a_ms)
            b_x = self._ms_to_x(self._loop_b_ms)
            loop_x = min(a_x, b_x)
            loop_w = abs(b_x - a_x)
            if loop_w > 0:
                painter.fillRect(QRectF(loop_x, rect.top(), loop_w, rect.height()), _LOOP_AREA)

        # Center line (nol amplitudo)
        painter.setPen(QPen(_CENTERLINE, 1))
        painter.drawLine(0, rect.height() // 2, rect.width(), rect.height() // 2)

        # Render peaks
        self._draw_peaks(painter, QRectF(rect))

        # Playhead
        ph_x = self._ms_to_x(self._position_ms)
        painter.setPen(QPen(_PLAYHEAD, 2))
        painter.drawLine(int(ph_x), rect.top(), int(ph_x), rect.bottom())

        # Render markers (V0.5): garis + label text box
        painter.setFont(self._label_font)
        for m in self._markers:
            x = self._ms_to_x(m.time_ms)
            if x < -50 or x > rect.width() + 50:
                continue
            color = QColor(m.color) if m.color else QColor("#C43A31")
            selected = m.id == self._selected_marker_id
            dragging = m.id == self._drag_marker_id
            # Garis penanda
            pen_w = 3 if selected else 2
            painter.setPen(QPen(color, pen_w))
            painter.drawLine(
                int(x),
                rect.top() + _MARKER_LABEL_H + 2,
                int(x),
                rect.bottom(),
            )
            fm = painter.fontMetrics()
            label = m.label or "M?"
            label_w = min(120, max(22, fm.horizontalAdvance(label) + 8))
            label_rect = QRectF(x - label_w / 2.0, rect.top(), label_w, _MARKER_LABEL_H)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(120) if selected else color, 1))
            painter.drawRoundedRect(label_rect, 3, 3)
            # Teks label (putih agar terbaca pada latar berwarna)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)
            if dragging:
                # Indikator drag tebal di sekitar label
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_PLAYHEAD, 1, Qt.PenStyle.DashLine))
                painter.drawRect(label_rect.adjusted(-2, -2, 2, 2))

    def _draw_peaks(self, painter: QPainter, rect: QRectF) -> None:
        if self._peaks is None or self._duration_ms <= 0:
            return
        bucket_ms = self._peaks.level_for_zoom(self._pps)
        level = self._peaks.levels.get(bucket_ms)
        if level is None or level.size == 0:
            return
        level = level.astype(np.float32)

        view_start_ms = self._offset_ms
        view_end_ms = self._offset_ms + self._viewport_duration_ms() + 1

        i_start = max(0, view_start_ms // bucket_ms)
        i_end = min(len(level), (view_end_ms // bucket_ms) + 1)
        if i_end <= i_start:
            return
        slice_ = level[i_start:i_end]

        mid_y = rect.height() / 2.0
        scale = (rect.height() / 2.0 - 4.0) / 32767.0

        painter.setPen(QPen(_WAVE_OUTLINE, 1))
        min_cols = slice_[:, 0]
        max_cols = slice_[:, 1]

        # Skala ke float pixel
        ys_min = mid_y + min_cols * scale  # tipe: np.ndarray
        ys_max = mid_y + max_cols * scale

        # Draw outline dulu
        xs_start = self._ms_to_x(i_start * bucket_ms)
        bucket_px = bucket_ms * self._pps / 1000.0

        # Untuk performa, gunakan garis satu-per-satu (N ratusan hingga ribuan)
        painter.setPen(QPen(_WAVE, 1))
        for i in range(len(slice_)):
            x = xs_start + i * bucket_px
            x2 = x + max(1.0, bucket_px - 0.5)
            y1 = float(ys_min[i])
            y2 = float(ys_max[i])
            painter.fillRect(QRectF(x, y2, x2 - x, y1 - y2), _WAVE)

    # ------------------------------------------------------------------
    # Interaksi mouse (V0.5: support marker select/drag + double-click add)
    # ------------------------------------------------------------------
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._duration_ms <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        ms = self._x_to_ms(float(event.position().x()))
        self.marker_add_requested.emit(int(ms))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._duration_ms <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        cursor_x = float(event.position().x())

        # Prioritas 1: user menekan tepat di atas marker → select + prepare drag
        hit = self._hit_marker(cursor_x)
        if hit is not None:
            self._drag_marker_id = hit.id
            self._drag_click_offset_px = cursor_x - self._ms_to_x(hit.time_ms)
            self._selected_marker_id = hit.id
            self.marker_selected_changed.emit(hit.id)
            self.update()
            return

        # Prioritas 2: klik area kosong → seek + deselect marker
        ms = self._x_to_ms(cursor_x)
        self._selected_marker_id = ""
        self.marker_selected_changed.emit("")
        self.seek_requested.emit(ms)
        self.set_position(ms)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_marker_id is None:
            return
        new_x = float(event.position().x()) - self._drag_click_offset_px
        new_ms = self._x_to_ms(new_x)
        # Emit real-time preview (MainWindow paksa enforce gap sebelum mutate collection)
        self.marker_drag_moved.emit(self._drag_marker_id, new_ms)
        # Update visual preview (tanpa ubah state collection)
        for m in self._markers:
            if m.id == self._drag_marker_id:
                m.time_ms = new_ms
                break
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_marker_id is None or event.button() != Qt.MouseButton.LeftButton:
            return
        marker_id = self._drag_marker_id
        self._drag_marker_id = None
        new_x = float(event.position().x()) - self._drag_click_offset_px
        new_ms = self._x_to_ms(new_x)
        self.marker_dragged.emit(marker_id, int(new_ms))
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        modifiers = event.modifiers()
        if (
            modifiers & Qt.KeyboardModifier.ControlModifier
            or modifiers & Qt.KeyboardModifier.ShiftModifier
        ):
            # Zoom around cursor
            angle = event.angleDelta().y()
            if angle == 0:
                return
            factor = 1.25 if angle > 0 else 1 / 1.25
            cursor_ms = self._x_to_ms(float(event.position().x()))
            self._pps = max(self._MIN_PPS, min(self._MAX_PPS, self._pps * factor))
            # Scroll supaya pixel di bawah cursor tetap pada ms yang sama
            new_x = (cursor_ms - self._offset_ms) * self._pps / 1000.0
            self._offset_ms = int(
                round(cursor_ms - float(event.position().x()) * 1000.0 / self._pps)
            )
            self._clamp_offset()
            _ = new_x  # disimpan untuk debug, sementara tidak dipakai
            self.zoom_requested.emit(self._pps)
            self.update()
        else:
            # Scroll horizontal
            delta = event.angleDelta().x() or event.angleDelta().y()
            if delta == 0:
                return
            step_ms = max(100, self._viewport_duration_ms() // 10)
            move_ms = int(round(delta / 120.0 * step_ms))
            self._offset_ms = max(
                0,
                min(
                    max(0, self._duration_ms - self._viewport_duration_ms()),
                    self._offset_ms - move_ms,
                ),
            )
            self.update()
