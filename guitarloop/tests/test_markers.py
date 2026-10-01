"""Uji unit MarkerCollection (V0.5 §6.1)."""

from __future__ import annotations

import pytest

from guitarloop.core.markers import MIN_MARKER_GAP_MS, Marker, MarkerCollection


@pytest.fixture()
def empty() -> MarkerCollection:
    return MarkerCollection()


@pytest.fixture()
def col5() -> MarkerCollection:
    """5 markers dengan waktu 0ms, 5000ms, 10000ms, 15000ms, 20000ms."""
    c = MarkerCollection()
    assert c.add(0) is not None
    assert c.add(5_000) is not None
    assert c.add(10_000) is not None
    assert c.add(15_000) is not None
    assert c.add(20_000) is not None
    return c


class TestTambahMarker:
    def test_tambah_auto_label_urut(self, empty: MarkerCollection) -> None:
        m1 = empty.add(10_000)
        m2 = empty.add(1_000)  # lebih awal -> harusnya jadi M1 (urut waktu)
        m3 = empty.add(5_000)
        assert m1 is not None and m2 is not None and m3 is not None
        labels = [m.label for m in empty]
        # Urut waktu: 1000, 5000, 10000
        assert labels == ["M1", "M2", "M3"]

    def test_tambah_terlalu_dekat_return_none(self, empty: MarkerCollection) -> None:
        assert empty.add(5_000) is not None
        # Tambah pada 5000 + MIN-1 → gagal
        assert empty.add(5_000 + MIN_MARKER_GAP_MS - 1) is None
        # Tambah pada 5000 + MIN → berhasil
        assert empty.add(5_000 + MIN_MARKER_GAP_MS) is not None
        assert len(empty) == 2

    def test_min_gap_ms_50(self, empty: MarkerCollection) -> None:
        # PRD §6.1: minimal jarak 50 ms
        assert MIN_MARKER_GAP_MS == 50


class TestHapusRename:
    def test_hapus_mengurutkan_label_kembali(self, col5: MarkerCollection) -> None:
        # Hapus marker index ke-2 (10000ms = M3)
        mid = col5[2].id
        assert col5.remove(mid) is True
        labels = [m.label for m in col5]
        # Sisa 4 marker dengan urut waktu → M1..M4 (tidak boleh lompong nomor)
        assert labels == ["M1", "M2", "M3", "M4"]

    def test_rename_custom_dipertahankan(self, col5: MarkerCollection) -> None:
        mid = col5[1].id  # M2
        assert col5.rename(mid, "Intro") is True
        # Tambah marker baru di tengah antara M1 dan Intro
        added = col5.add(2_500)
        assert added is not None
        labels = [m.label for m in col5]
        # "Intro" tidak boleh diganti ke Mx karena user rename manual
        assert "Intro" in labels
        assert labels.count("Intro") == 1

    def test_rename_empty_kembali_auto(self, col5: MarkerCollection) -> None:
        mid = col5[0].id
        col5.rename(mid, "Intro")
        col5.rename(mid, "")  # kosong → revert auto
        assert col5[0].label == "M1"


class TestPindahDanNudge:
    def test_pindah_tabrakan_batal(self, col5: MarkerCollection) -> None:
        # Coba geser marker index 0 (0ms) ke 4990ms = dalam <50ms jarak dgn M2 (5000ms)
        mid0 = col5[0].id
        assert col5.move(mid0, 4_990, enforce_gap=True) is False
        # Posisi tidak berubah
        assert col5[0].time_ms == 0

    def test_pindah_berhasil(self, col5: MarkerCollection) -> None:
        mid = col5[0].id
        assert col5.move(mid, 2_500) is True
        # Urut berubah: [2500, 5000, 10000, 15000, 20000]
        assert col5[0].time_ms == 2_500
        assert len(col5) == 5

    def test_nudge_halus(self, col5: MarkerCollection) -> None:
        mid = col5[0].id
        assert col5.nudge(mid, +100) is True
        assert col5[0].time_ms == 100
        # Nudge Ctrl +1 ms
        assert col5.nudge(mid, +1) is True
        assert col5[0].time_ms == 101
        # Nudge Shift +100 ms
        assert col5.nudge(mid, +100) is True
        assert col5[0].time_ms == 201

    def test_find_nearest(self, col5: MarkerCollection) -> None:
        # Cari waktu 7500 → terdekat adalah 5000 atau 10000
        nearest = col5.find_nearest(7_500)
        assert nearest is not None
        assert nearest.time_ms in (5_000, 10_000)
        # Cari tepat 5000 → ketemu M2
        m5k = col5.find_nearest(5_000)
        assert m5k is not None
        assert m5k.time_ms == 5_000


class TestGantiSemua:
    def test_replace_all_sorted(self, empty: MarkerCollection) -> None:
        lst = [
            Marker(Marker.new_id(), time_ms=20_000, label=""),
            Marker(Marker.new_id(), time_ms=5_000, label=""),
            Marker(Marker.new_id(), time_ms=0, label=""),
        ]
        empty.replace_all(lst)
        assert [m.time_ms for m in empty] == [0, 5_000, 20_000]
        # Auto-label M1..M3
        assert [m.label for m in empty] == ["M1", "M2", "M3"]
