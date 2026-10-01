"""Uji penyimpanan SQLite (§8.6) dan persistensi (§6.5).

Cover kriteria penerimaan:

- Pulihkan setelah tutup/buka (db file sama)

- Penanda tetap terbaca meski file MP3 dipindahkan (berdasarkan audio_hash)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from guitarloop.core.markers import MarkerCollection
from guitarloop.core.storage import Storage


@pytest.fixture()
def fresh_db(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "test_guitarloop.db")


def _make_track(storage: Storage, *, audio_hash: str, title: str) -> int:
    return storage.upsert_track(
        audio_hash=audio_hash,
        path=Path(f"C:/dummy/{audio_hash}.mp3"),
        title=title,
        artist="Artis",
        duration_ms=180_000,
    )


class TestTracksCRUD:
    def test_upsert_dan_get_track(self, fresh_db: Storage) -> None:
        tid = _make_track(fresh_db, audio_hash="HASH001", title="Lagu A")
        assert tid > 0
        got = fresh_db.get_track("HASH001")
        assert got is not None
        assert got["id"] == tid
        assert got["title"] == "Lagu A"
        assert got["audio_hash"] == "HASH001"

    def test_upsert_same_hash_return_same_id(self, fresh_db: Storage) -> None:
        t1 = _make_track(fresh_db, audio_hash="SAME", title="Judul 1")
        t2 = _make_track(fresh_db, audio_hash="SAME", title="Judul 2")
        assert t1 == t2
        # Judul terakhir tersimpan
        got = fresh_db.get_track("SAME")
        assert got is not None
        assert got["title"] == "Judul 2"


class TestMarkersPersisten:
    def test_simpan_dan_muat_markers(self, fresh_db: Storage) -> None:
        tid = _make_track(fresh_db, audio_hash="HASHMRK", title="Lagu Marker")
        col = MarkerCollection()
        col.add(0)
        col.add(5_000)
        col.add(12_345)
        mid2 = col[1].id
        col.rename(mid2, "Intro")

        # Simpan ke DB
        fresh_db.save_markers(tid, list(col.all))
        fresh_db.force_flush()

        # Buat Storage BARU (buka ulang db) → pastikan masih ada
        storage2 = Storage(fresh_db._path)  # noqa: SLF001 (test butuh akses path)
        loaded = storage2.load_markers(tid)
        assert len(loaded) == 3
        # Urut by time
        times = sorted(m.time_ms for m in loaded)
        assert times == [0, 5_000, 12_345]
        # Label "Intro" tersimpan
        labels = {m.time_ms: m.label for m in loaded}
        assert labels[5_000] == "Intro"

    def test_update_markers_replace_all(self, fresh_db: Storage) -> None:
        tid = _make_track(fresh_db, audio_hash="REPLACE", title="R")
        col = MarkerCollection()
        col.add(100)
        fresh_db.save_markers(tid, list(col.all))

        # Update markers: hapus semua, ganti baru beda isi
        col2 = MarkerCollection()
        col2.add(9_999)
        col2.add(20_000)
        col2.add(30_000)
        fresh_db.save_markers(tid, list(col2.all))
        fresh_db.force_flush()

        got = fresh_db.load_markers(tid)
        assert len(got) == 3
        assert sorted(m.time_ms for m in got) == [9_999, 20_000, 30_000]

    def test_rename_path_tetap_sama_hash_markers_ada(self, fresh_db: Storage) -> None:
        """Kriteria PRD: Memindahkan file MP3 → penanda tetap terbaca via hash."""
        # Insert awal dengan path A
        tid = fresh_db.upsert_track(
            audio_hash="SAMEHASH",
            path=Path("C:/FolderLama/song.mp3"),
            title="Tetap terbaca",
            artist="A",
            duration_ms=60_000,
        )
        col = MarkerCollection()
        col.add(1_000)
        col.add(7_500)
        fresh_db.save_markers(tid, list(col.all))

        # Insert ulang dengan hash SAMA tapi path BEDA (user pindahkan file MP3)
        tid2 = fresh_db.upsert_track(
            audio_hash="SAMEHASH",
            path=Path("D:/FolderBaru/song_rename.mp3"),
            title="Tetap terbaca",
            artist="A",
            duration_ms=60_000,
        )
        # Track ID SAMA karena hash unik (upsert, bukan insert baru)
        assert tid == tid2
        markers = fresh_db.load_markers(tid2)
        assert len(markers) == 2


class TestTrackSettings:
    def test_simpan_muat_settings_lengkap(self, fresh_db: Storage) -> None:
        tid = _make_track(fresh_db, audio_hash="SETTINGS1", title="S")
        fresh_db.save_track_settings(
            track_id=tid,
            speed=0.65,
            volume=0.55,
            loop_mode="a_b",
            loop_a=1000,
            loop_b=5000,
            loop_after="continue",
            repeat_count=7,
            gap_ms=500,
            preroll_ms=2000,
            ramp_json='{"mode":"linear"}',
        )
        fresh_db.force_flush()
        s = fresh_db.load_track_settings(tid)
        assert abs(s["speed"] - 0.65) < 1e-6
        assert abs(s["volume"] - 0.55) < 1e-6
        assert s["loop_mode"] == "a_b"
        assert s["loop_a"] == 1000
        assert s["loop_b"] == 5000
        assert s["loop_after"] == "continue"
        assert s["repeat_count"] == 7
        assert s["gap_ms"] == 500
        assert s["preroll_ms"] == 2000
        assert s["ramp_json"] == '{"mode":"linear"}'
