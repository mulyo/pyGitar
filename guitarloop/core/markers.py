"""Model dan operasi penanda (marker) audio.

Spesifikasi PRD §6.1:

- Atribut: id, time_ms, label, color, note

- Auto label M1, M2, ... urut waktu

- Min jarak antar-penanda 50 ms

- Operasi: tambah, hapus, ganti nama, pindah, nudge

- Urut berdasarkan time_ms ASC
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

# PRD §6.1: minimal jarak 50 ms
MIN_MARKER_GAP_MS = 50
DEFAULT_COLORS = [
    "#C43A31",  # merah
    "#3F7EA3",  # biru
    "#5A8F3C",  # hijau
    "#8E5AAA",  # ungu
    "#CC8A2C",  # oranye
    "#2F8F8F",  # tosca
    "#A63D6A",  # magenta
]


@dataclass(slots=True)
class Marker:
    """Satu titik penanda audio."""

    id: str
    time_ms: int
    label: str = ""
    color: str = DEFAULT_COLORS[0]
    note: str = ""

    @staticmethod
    def new_id() -> str:
        """Buat ID unik (8 karakter hex pertama UUID4, cukup unik per lagu)."""
        return uuid.uuid4().hex[:8]


class MarkerCollection:
    """Kumpulan penanda yang selalu terurut berdasarkan waktu."""

    def __init__(self, markers: list[Marker] | None = None) -> None:
        self._markers: list[Marker] = []
        self._min_gap = MIN_MARKER_GAP_MS
        self._next_color_idx = 0
        if markers:
            for m in markers:
                self._markers.append(
                    Marker(
                        id=m.id,
                        time_ms=m.time_ms,
                        label=m.label,
                        color=m.color,
                        note=m.note,
                    )
                )
            self._sort()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _sort(self) -> None:
        self._markers.sort(key=lambda m: m.time_ms)
        self._renumber_labels_auto()

    def _renumber_labels_auto(self) -> None:
        """Label yang masih default (Mxxx) di-renumber ulang sesuai urutan."""
        counter = 0
        for m in self._markers:
            stripped = m.label.strip()
            if _is_auto_label(stripped):
                counter += 1
                m.label = f"M{counter}"
            elif not stripped:
                counter += 1
                m.label = f"M{counter}"
        self._next_color_idx = len(self._markers) % len(DEFAULT_COLORS)

    def _next_color(self) -> str:
        color = DEFAULT_COLORS[self._next_color_idx % len(DEFAULT_COLORS)]
        self._next_color_idx += 1
        return color

    def _validate_gap(self, time_ms: int, exclude_id: str | None = None) -> bool:
        return (
            self.find_nearest(time_ms, exclude_id=exclude_id) is None
            or self._nearest_distance >= self._min_gap
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._markers)

    def __iter__(self) -> Iterator[Marker]:
        return iter(list(self._markers))

    def __getitem__(self, index: int) -> Marker:
        return self._markers[index]

    @property
    def all(self) -> list[Marker]:
        """Return snapshot list marker (tidak bisa mutate internal)."""
        return [Marker(m.id, m.time_ms, m.label, m.color, m.note) for m in self._markers]

    @property
    def min_gap_ms(self) -> int:
        return self._min_gap

    def get(self, marker_id: str) -> Marker | None:
        for m in self._markers:
            if m.id == marker_id:
                return m
        return None

    def index_of(self, marker_id: str) -> int:
        for i, m in enumerate(self._markers):
            if m.id == marker_id:
                return i
        return -1

    _nearest_distance: int = 0  # temp set oleh find_nearest untuk validasi gap

    def find_nearest(self, time_ms: int, *, exclude_id: str | None = None) -> Marker | None:
        """Return marker terdekat dengan time_ms (bisa exclude by id)."""
        best: Marker | None = None
        best_dist = 10**12
        self._nearest_distance = best_dist
        for m in self._markers:
            if exclude_id is not None and m.id == exclude_id:
                continue
            d = abs(m.time_ms - time_ms)
            if d < best_dist:
                best_dist = d
                best = m
        self._nearest_distance = best_dist if best is not None else 0
        return best

    # ------------------------------------------------------------------
    # Mutasi
    # ------------------------------------------------------------------
    def add(
        self,
        time_ms: int,
        *,
        label: str | None = None,
        color: str | None = None,
        enforce_gap: bool = True,
    ) -> Marker | None:
        """Tambah penanda di time_ms. Return Marker atau None jika bentrok jarak."""
        t = max(0, int(time_ms))
        if enforce_gap and not self._validate_gap(t):
            return None
        new_marker = Marker(
            id=Marker.new_id(),
            time_ms=t,
            label=label or "",
            color=color or self._next_color(),
        )
        self._markers.append(new_marker)
        self._sort()
        return new_marker

    def remove(self, marker_id: str) -> bool:
        for i, m in enumerate(self._markers):
            if m.id == marker_id:
                del self._markers[i]
                self._sort()
                return True
        return False

    def clear(self) -> None:
        self._markers.clear()
        self._sort()

    def rename(self, marker_id: str, new_label: str) -> bool:
        m = self.get(marker_id)
        if m is None:
            return False
        stripped = new_label.strip()
        if not stripped:
            # User kosongkan → kembalikan auto-label (nanti di _sort di-renumber)
            m.label = ""
            self._sort()
            return True
        m.label = stripped
        # Jangan renumber jika user berikan nama custom
        return True

    def set_note(self, marker_id: str, note: str) -> bool:
        m = self.get(marker_id)
        if m is None:
            return False
        m.note = note
        return True

    def set_color(self, marker_id: str, color: str) -> bool:
        m = self.get(marker_id)
        if m is None:
            return False
        m.color = color
        return True

    def move(self, marker_id: str, new_time_ms: int, *, enforce_gap: bool = True) -> bool:
        """Pindahkan waktu marker. Return False jika bentrok / id tidak ada."""
        m = self.get(marker_id)
        if m is None:
            return False
        t = max(0, int(new_time_ms))
        if t == m.time_ms:
            return True
        if enforce_gap and not self._validate_gap(t, exclude_id=marker_id):
            return False
        m.time_ms = t
        self._sort()
        return True

    def nudge(self, marker_id: str, delta_ms: int, *, enforce_gap: bool = True) -> bool:
        """Geser waktu marker sebanyak delta_ms (positif = maju)."""
        m = self.get(marker_id)
        if m is None:
            return False
        return self.move(marker_id, m.time_ms + int(delta_ms), enforce_gap=enforce_gap)

    def replace_all(self, markers: list[Marker]) -> None:
        """Override seluruh isi collection (digunakan saat load dari DB)."""
        self._markers.clear()
        for m in markers:
            self._markers.append(Marker(m.id, m.time_ms, m.label, m.color, m.note))
        self._sort()


def _is_auto_label(text: str) -> bool:
    """Return True jika text match pola M<digit> (auto-label)."""
    if not text.startswith("M") or len(text) < 2:
        return False
    digits = text[1:]
    return digits.isdigit()


# Helper type untuk debounce storage
OnChangeCallback = Callable[[], None]
