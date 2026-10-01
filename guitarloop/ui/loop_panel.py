"""Panel kontrol loop sesuai PRD §7 (panel kiri bawah) & §6.2/§6.3.

- Mode dropdown: OFF / A-B / Bagian / Awal→Penanda / Penanda→Akhir

- Dropdown A & B (untuk mode A-B) atau dropdown marker tunggal

- Numeric ulangan + checkbox ∞

- Label status: "Ulangan n/N" atau "∞"
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from guitarloop.core.loop_controller import LoopAfterAction, LoopMode
from guitarloop.utils.i18n import t

_MODE_LABELS: dict[LoopMode, str] = {
    LoopMode.OFF: t("loop_mode_off", default="— Mati —"),
    LoopMode.A_B: t("loop_mode_ab", default="A → B"),
    LoopMode.BAGIAN: t("loop_mode_bagian", default="Bagian (Mn → Mn+1)"),
    LoopMode.AWAL_MARKER: t("loop_mode_awal", default="Awal → Penanda"),
    LoopMode.MARKER_AKHIR: t("loop_mode_akhir", default="Penanda → Akhir"),
}

_AFTER_LABELS: dict[LoopAfterAction, str] = {
    LoopAfterAction.STOP: t("loop_after_stop", default="Berhenti"),
    LoopAfterAction.CONTINUE: t("loop_after_cont", default="Lanjut play"),
}


class LoopPanel(QWidget):
    """Panel kontrol loop (ditempatkan di dock kiri / bottom)."""

    enabled_toggled = Signal(bool)  # aktif/nonaktif (shortcut L)
    mode_changed = Signal(object)  # LoopMode
    ab_marker_changed = Signal(str, str)  # marker_id_A, marker_id_B
    marker_index_changed = Signal(int)  # untuk BAGIAN/AWAL/AKHIR
    repeat_changed = Signal(int)  # 0 = ∞
    after_action_changed = Signal(object)  # LoopAfterAction

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        title = QLabel(t("loop_title", default="LOOP"))
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        # ---- Checkbox utama AKTIFKAN LOOP (shortcut L di main_window toggle ini)
        self.chk_enable = QCheckBox(t("loop_enable", default="✅ Aktifkan Pengulangan"), self)
        ef = self.chk_enable.font()
        ef.setBold(True)
        self.chk_enable.setFont(ef)
        self.chk_enable.setChecked(False)
        root.addWidget(self.chk_enable)

        box = QGroupBox(t("loop_group", default="Kontrol Pengulangan"), self)
        form = QFormLayout(box)
        form.setSpacing(6)

        self.cmb_mode = QComboBox(self)
        for mode, label in _MODE_LABELS.items():
            self.cmb_mode.addItem(label, mode)

        # A & B marker dropdowns (hanya muncul untuk mode A-B; tapi sediakan
        # tetap selalu terlihat agar layout tidak berubah-ubah / jitter)
        row_ab = QHBoxLayout()
        row_ab.setSpacing(4)
        self.cmb_a = QComboBox(self)
        self.cmb_a.setMinimumWidth(80)
        self.cmb_b = QComboBox(self)
        self.cmb_b.setMinimumWidth(80)
        self.lbl_a = QLabel(t("loop_A", default="A:"), self)
        self.lbl_b = QLabel(t("loop_B", default="B:"), self)
        row_ab.addWidget(self.lbl_a)
        row_ab.addWidget(self.cmb_a, 1)
        row_ab.addWidget(self.lbl_b)
        row_ab.addWidget(self.cmb_b, 1)
        row_ab_wrap = QWidget()
        row_ab_wrap.setLayout(row_ab)

        # Marker dropdown tunggal (untuk BAGIAN / AWAL / AKHIR mode)
        row_marker = QHBoxLayout()
        self.cmb_marker = QComboBox(self)
        row_marker.addWidget(QLabel(t("loop_marker", default="Penanda:"), self))
        row_marker.addWidget(self.cmb_marker, 1)
        row_marker_wrap = QWidget()
        row_marker_wrap.setLayout(row_marker)

        # Repeat count + ∞
        self.spin_repeat = QSpinBox(self)
        self.spin_repeat.setRange(1, 99)
        self.spin_repeat.setValue(5)
        self.chk_infinite = QCheckBox(t("loop_inf", default="∞ (tak terbatas)"), self)

        # After action
        self.cmb_after = QComboBox(self)
        for action, label in _AFTER_LABELS.items():
            self.cmb_after.addItem(label, action)

        # Status iteration (DIPERBESAR agar jelas terlihat)
        # ---- BARIS 1: COUNTER BESAR (n/N) font 20pt)
        self.lbl_counter_big = QLabel("0 / 0", self)
        cf = self.lbl_counter_big.font()
        cf.setPointSize(18)
        cf.setBold(True)
        self.lbl_counter_big.setFont(cf)
        self.lbl_counter_big.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_counter_big.setMinimumHeight(44)
        self.lbl_counter_big.setStyleSheet(
            "color: #888888; background-color: #222226;"
            " border-radius: 6px; padding: 4px 8px; margin-top: 2px;"
        )
        # ---- BARIS 2: keterangan status detail (aktif / selesai
        self.lbl_status = QLabel(t("loop_status_idle", default="Siap (tidak loop)"), self)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        sf = self.lbl_status.font()
        sf.setBold(True)
        sf.setPointSize(10)
        self.lbl_status.setFont(sf)
        self.lbl_status.setStyleSheet("color: #3F7EA3;")

        form.addRow(t("loop_mode", default="Mode:"), self.cmb_mode)
        form.addRow(t("loop_ab_row", default="A & B:"), row_ab_wrap)
        form.addRow(t("loop_marker_row", default="Penanda:"), row_marker_wrap)
        form.addRow(t("loop_repeat", default="Ulangan:"), self.spin_repeat)
        form.addRow("", self.chk_infinite)
        form.addRow(t("loop_after", default="Selesai:"), self.cmb_after)
        form.addRow(t("loop_counter_row", default="Counter:"), self.lbl_counter_big)
        form.addRow(t("loop_status", default="Status:"), self.lbl_status)

        root.addWidget(box)

        # --- Signal wiring ---
        self.chk_enable.toggled.connect(self.enabled_toggled.emit)
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        self.cmb_a.currentIndexChanged.connect(self._emit_ab)
        self.cmb_b.currentIndexChanged.connect(self._emit_ab)
        self.cmb_marker.currentIndexChanged.connect(
            lambda idx: self.marker_index_changed.emit(max(0, idx))
        )
        self.spin_repeat.valueChanged.connect(self._on_repeat_changed)
        self.chk_infinite.toggled.connect(self._on_infinite_toggled)
        self.cmb_after.currentIndexChanged.connect(
            lambda _i: self.after_action_changed.emit(
                self.cmb_after.currentData() or LoopAfterAction.STOP
            )
        )

        self._update_enables()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_markers(self, markers: Iterable[object], *, preserve_ids: bool = True) -> None:
        """Isi semua combo marker dengan item baru. `markers` adalah Marker list."""
        ids = []
        labels_a, labels_b, labels_m = [], [], []
        for m in markers:
            mid = getattr(m, "id", str(m))
            label = getattr(m, "label", mid)
            t_ms = int(getattr(m, "time_ms", 0))
            from guitarloop.utils.timefmt import format_ms

            t_str = format_ms(t_ms)
            ids.append(mid)
            labels_a.append((f"{label} ({t_str})", mid))
            labels_b.append((f"{label} ({t_str})", mid))
            labels_m.append((f"{label} ({t_str})", mid))

        self._rebuild_combo(self.cmb_a, labels_a, preserve_ids)
        self._rebuild_combo(self.cmb_b, labels_b, preserve_ids)
        self._rebuild_combo(self.cmb_marker, labels_m, preserve_ids)

    def _rebuild_combo(
        self, cmb: QComboBox, items: list[tuple[str, str]], preserve_ids: bool
    ) -> None:
        prev = cmb.currentData() if preserve_ids else None
        cmb.blockSignals(True)
        cmb.clear()
        for label, mid in items:
            cmb.addItem(label, mid)
        if prev:
            idx = cmb.findData(prev)
            if idx >= 0:
                cmb.setCurrentIndex(idx)
        cmb.blockSignals(False)

    def set_mode(self, mode: LoopMode) -> None:
        # Sync enable checkbox: OFF = uncheck, lain = check
        want = mode != LoopMode.OFF
        if self.chk_enable.isChecked() != want:
            self.chk_enable.blockSignals(True)
            self.chk_enable.setChecked(want)
            self.chk_enable.blockSignals(False)
        idx = self.cmb_mode.findData(mode)
        if idx >= 0 and idx != self.cmb_mode.currentIndex():
            self.cmb_mode.blockSignals(True)
            self.cmb_mode.setCurrentIndex(idx)
            self.cmb_mode.blockSignals(False)
        self._update_enables()

    def set_selected_marker_index(self, index: int) -> None:
        if 0 <= index < self.cmb_marker.count():
            self.cmb_marker.blockSignals(True)
            self.cmb_marker.setCurrentIndex(index)
            self.cmb_marker.blockSignals(False)

    def set_repeat(self, count: int) -> None:
        self.chk_infinite.blockSignals(True)
        self.spin_repeat.blockSignals(True)
        self.chk_infinite.setChecked(count <= 0)
        self.spin_repeat.setValue(max(1, count) if count else 5)
        self.spin_repeat.setEnabled(count > 0)
        self.chk_infinite.blockSignals(False)
        self.spin_repeat.blockSignals(False)

    def set_after_action(self, action: LoopAfterAction) -> None:
        idx = self.cmb_after.findData(action)
        if idx >= 0:
            self.cmb_after.blockSignals(True)
            self.cmb_after.setCurrentIndex(idx)
            self.cmb_after.blockSignals(False)

    def set_iteration_status(self, current: int, total: int | None) -> None:
        # --- BARIS ATAS: counter BESAR (n/N atau ∞n)
        if total is None:
            c_big = f"∞ {current}"
        elif total <= 0:
            c_big = "0 / 0"
        else:
            c_big = f"{min(current, total)} / {total}"
        self.lbl_counter_big.setText(c_big)

        # Warna counter: MERAH jika sedang loop (aktif), HIJAU selesai, ABU idle.
        try:
            if total is None:
                # Infinite loop (∞) → biru
                self.lbl_counter_big.setStyleSheet(
                    "color: #E6B300; background-color: #222226;"
                    " border-radius: 6px; padding: 4px 8px; margin-top: 2px;"
                )
            elif total > 0 and current >= total:
                # Selesai → hijau stabilo
                self.lbl_counter_big.setStyleSheet(
                    "color: #2ECC71; background-color: #143A23;"
                    " border-radius: 6px; padding: 4px 8px; margin-top: 2px; font-weight: 800;"
                )
            elif current > 0:
                # Sedang berjalan → merah / kuning
                self.lbl_counter_big.setStyleSheet(
                    "color: #FF5E5E; background-color: #3A1514;"
                    " border-radius: 6px; padding: 4px 8px; margin-top: 2px;"
                )
            else:
                # Idle menunggu start
                self.lbl_counter_big.setStyleSheet(
                    "color: #888888; background-color: #222226;"
                    " border-radius: 6px; padding: 4px 8px; margin-top: 2px;"
                )
        except Exception:
            pass

        # --- BARIS BAWAH: pesan keterangan
        if total is None:
            if current == 0:
                msg = t("loop_inf_wait", default="∞ Loop AKTIF (menunggu start)")
            else:
                msg = t("loop_inf_run", default="∞ Loop ke-{n}", n=current)
        else:
            if total == 0:
                msg = t("loop_status_idle", default="Siap (tidak loop)")
            elif current >= total:
                msg = t(
                    "loop_done",
                    default="✅ SELESAI {total}x ulangan",
                    total=total,
                )
            else:
                msg = t(
                    "loop_status_run",
                    default="Sedang ulangan {n}/{total} (sisa {sisa})",
                    n=min(current, total),
                    total=total,
                    sisa=max(0, total - current),
                )
        self.lbl_status.setText(msg)

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------
    def _update_enables(self) -> None:
        mode = self.cmb_mode.currentData() or LoopMode.OFF
        enabled_chk = self.chk_enable.isChecked()
        active = enabled_chk and mode != LoopMode.OFF
        self.cmb_mode.setEnabled(enabled_chk)
        self.cmb_a.setEnabled(active and mode == LoopMode.A_B)
        self.cmb_b.setEnabled(active and mode == LoopMode.A_B)
        self.cmb_marker.setEnabled(
            active and mode in (LoopMode.BAGIAN, LoopMode.AWAL_MARKER, LoopMode.MARKER_AKHIR)
        )
        self.spin_repeat.setEnabled(enabled_chk and not self.chk_infinite.isChecked())
        self.chk_infinite.setEnabled(enabled_chk)
        self.cmb_after.setEnabled(enabled_chk)
        self.lbl_a.setEnabled(self.cmb_a.isEnabled())
        self.lbl_b.setEnabled(self.cmb_b.isEnabled())

    def _on_mode_changed(self, _idx: int) -> None:
        mode = self.cmb_mode.currentData() or LoopMode.OFF
        self._update_enables()
        self.mode_changed.emit(mode)
        if mode == LoopMode.A_B:
            self._emit_ab()
        elif mode != LoopMode.OFF:
            self.marker_index_changed.emit(max(0, self.cmb_marker.currentIndex()))

    def _emit_ab(self, *_args: object) -> None:
        id_a = self.cmb_a.currentData()
        id_b = self.cmb_b.currentData()
        if id_a and id_b:
            self.ab_marker_changed.emit(str(id_a), str(id_b))

    def _on_repeat_changed(self, val: int) -> None:
        if self.chk_infinite.isChecked():
            self.repeat_changed.emit(0)
        else:
            self.repeat_changed.emit(int(val))

    def _on_infinite_toggled(self, checked: bool) -> None:
        self.spin_repeat.setEnabled(not checked)
        self.repeat_changed.emit(0 if checked else max(1, self.spin_repeat.value()))
