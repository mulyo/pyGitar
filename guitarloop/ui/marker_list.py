"""Panel samping daftar penanda (marker) sesuai PRD §6.1 & §7 layout.

Fitur:

- Daftar penanda terurut (klik = lompat ke posisi)

- Tombol Tambah di playhead

- Tombol Hapus penanda terpilih

- Rename via F2 atau klik ganda edit inline QListWidgetItem

- Hapus via tombol Delete atau context menu
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from guitarloop.core.markers import Marker
from guitarloop.utils.i18n import t
from guitarloop.utils.timefmt import format_ms


class MarkerList(QWidget):
    """Panel samping: daftar marker + tombol Tambah/Hapus."""

    add_clicked = Signal()  # Minta MainWindow tambah di playhead
    remove_clicked = Signal(str)  # marker_id
    rename_requested = Signal(str, str)  # marker_id, new_label
    item_clicked = Signal(str)  # marker_id (lompat)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._markers: list[Marker] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self.lst = QListWidget(self)
        self.lst.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lst.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.lst.setAlternatingRowColors(True)
        self.lst.setIconSize(QSize(12, 12))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.btn_add = QPushButton(t("marker_btn_add", default="+ Tambah"), self)
        self.btn_del = QPushButton(t("marker_btn_del", default="Hapus"), self)
        self.btn_del.setEnabled(False)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_del)

        layout.addWidget(QLabel(t("marker_list_title", default="Daftar Penanda")))
        layout.addWidget(self.lst, 1)
        layout.addLayout(btn_row)

        # Signals
        self.btn_add.clicked.connect(self.add_clicked.emit)
        self.btn_del.clicked.connect(self._on_del_clicked)
        self.lst.itemClicked.connect(self._on_item_clicked)
        self.lst.itemChanged.connect(self._on_item_changed)
        self.lst.currentItemChanged.connect(self._on_current_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_markers(self, markers: Iterable[Marker], selected_id: str = "") -> None:
        self._markers = list(markers)
        self.lst.blockSignals(True)
        self.lst.clear()
        selected_row = -1
        for i, m in enumerate(self._markers):
            time_str = format_ms(m.time_ms, show_hours=False)
            label = m.label or f"M{i + 1}"
            text = f"{label:<10s} {time_str}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            item.setForeground(QColor(m.color) if m.color else QColor("#C43A31"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(m.note or f"ID {m.id} — klik ganda untuk rename")
            # Icon kecil berbentuk persegi warna marker (visualisasi cepat)
            icon_pix = _create_color_icon(m.color or "#C43A31")
            item.setIcon(QIcon(icon_pix))
            self.lst.addItem(item)
            if m.id == selected_id:
                selected_row = i
        if selected_row >= 0:
            self.lst.setCurrentRow(selected_row)
        self.btn_del.setEnabled(selected_row >= 0)
        self.lst.blockSignals(False)

    def selected_marker_id(self) -> str:
        item = self.lst.currentItem()
        if item is None:
            return ""
        val = item.data(Qt.ItemDataRole.UserRole)
        return str(val) if val else ""

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------
    def _on_del_clicked(self) -> None:
        mid = self.selected_marker_id()
        if mid:
            # Skip konfirmasi untuk speed, tapi beri popup agar user tahu.
            item = self.lst.currentItem()
            label = (item.text().split()[0]) if item else mid
            ok = QMessageBox.question(
                self,
                t("del_dlg_title", default="Hapus Penanda"),
                t(
                    "del_dlg_msg",
                    default="Hapus penanda '{label}'?",
                    label=label,
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ok == QMessageBox.StandardButton.Yes:
                self.remove_clicked.emit(mid)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        mid = item.data(Qt.ItemDataRole.UserRole)
        if mid:
            self.item_clicked.emit(str(mid))

    def _on_current_changed(
        self, _cur: QListWidgetItem | None, _prev: QListWidgetItem | None
    ) -> None:
        self.btn_del.setEnabled(self.lst.currentRow() >= 0)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        mid = item.data(Qt.ItemDataRole.UserRole)
        if not mid:
            return
        # Input edit hanya untuk bagian LABEL (sebelum spasi pertama). Jangan
        # biarkan user mengacak text waktu yang ditampilkan.
        text = item.text().strip()
        # Pertama, kembalikan format tampilan dengan waktu yang benar
        marker_obj = next((m for m in self._markers if m.id == mid), None)
        if marker_obj is None:
            return
        new_label = text.split(maxsplit=1)[0] if text else ""
        time_str = format_ms(marker_obj.time_ms)
        # Restore item text ke format baku
        self.lst.blockSignals(True)
        item.setText(f"{new_label or marker_obj.label:<10s} {time_str}")
        self.lst.blockSignals(False)
        if new_label and new_label != marker_obj.label:
            self.rename_requested.emit(str(mid), new_label)


def _create_color_icon(hex_color: str) -> QPixmap:
    """Buat QPixmap kecil 12x12 persegi warna untuk icon list."""
    from PySide6.QtGui import QBrush, QPainter, QPixmap

    pix = QPixmap(12, 12)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setBrush(QBrush(QColor(hex_color)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, 12, 12, 2, 2)
    painter.end()
    return pix
