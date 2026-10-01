"""Penyimpanan persisten SQLite.

Sesuai PRD §8.6: tabel `tracks`, `markers`, `track_settings`, `practice_log`.
Semua perubahan marker/settings disimpan otomatis dengan debounce 500 ms (§6.5).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from guitarloop.core.markers import Marker
from guitarloop.utils.paths import db_path, ensure_dirs

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  audio_hash TEXT UNIQUE NOT NULL,
  path TEXT,
  title TEXT,
  artist TEXT,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  last_opened TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS markers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  marker_uuid TEXT NOT NULL,
  time_ms INTEGER NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  color TEXT NOT NULL DEFAULT '#C43A31',
  note TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_markers_uuid ON markers(marker_uuid);
CREATE INDEX IF NOT EXISTS idx_markers_track_time ON markers(track_id, time_ms);

CREATE TABLE IF NOT EXISTS track_settings (
  track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
  speed REAL NOT NULL DEFAULT 1.0,
  volume REAL NOT NULL DEFAULT 0.8,
  loop_mode TEXT,
  loop_a INTEGER,
  loop_b INTEGER,
  loop_after TEXT NOT NULL DEFAULT 'stop',
  repeat_count INTEGER NOT NULL DEFAULT 5,
  gap_ms INTEGER NOT NULL DEFAULT 0,
  preroll_ms INTEGER NOT NULL DEFAULT 0,
  ramp_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_tracks_last_opened ON tracks(last_opened);
"""

# PRD §6.5: debounce 500 ms
_DEBOUNCE_DELAY_SEC = 0.5


class Storage:
    """Wrapper SQLite thread-safe dengan autosave debounced (§6.5)."""

    def __init__(self, path: Path | None = None) -> None:
        ensure_dirs()
        self._path = Path(path) if path else db_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.executescript(_SCHEMA)
                # -----------------------------------------------------------------
                # Schema MIGRATION (V0.1 → V0.5)
                # Jalankan ALTER TABLE satu per satu. Jika kolom sudah ada,
                # OperationalError dibuang (safe idempotent).
                # -----------------------------------------------------------------
                migrations_track_settings: list[tuple[str, str]] = [
                    # (kolom, spec)
                    ("loop_after", "TEXT NOT NULL DEFAULT 'stop'"),
                    ("repeat_count", "INTEGER NOT NULL DEFAULT 5"),
                    ("gap_ms", "INTEGER NOT NULL DEFAULT 0"),
                    ("preroll_ms", "INTEGER NOT NULL DEFAULT 0"),
                    ("ramp_json", "TEXT"),
                ]
                for col_name, col_spec in migrations_track_settings:
                    try:
                        cur.execute(f"ALTER TABLE track_settings ADD COLUMN {col_name} {col_spec}")
                    except sqlite3.OperationalError:
                        # Kolom sudah ada — OK, lanjut migration berikutnya.
                        pass
                migrations_tracks: list[tuple[str, str]] = []  # untuk V0.6+ nanti
                for col_name, col_spec in migrations_tracks:
                    try:
                        cur.execute(f"ALTER TABLE tracks ADD COLUMN {col_name} {col_spec}")
                    except sqlite3.OperationalError:
                        pass
            self._conn.commit()
        # Debounce timer untuk markers & settings (§6.5: 500 ms)
        self._debounce_lock = threading.Lock()
        self._pending_timer: threading.Timer | None = None

    def close(self) -> None:
        with self._debounce_lock:
            if self._pending_timer is not None:
                self._pending_timer.cancel()
                self._pending_timer = None
        # Flush sisa pending commit
        try:
            self._conn.commit()
        except Exception:
            pass
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def _schedule_flush(self) -> None:
        """Schedule commit setelah idle _DEBOUNCE_DELAY_SEC detik."""
        with self._debounce_lock:
            if self._pending_timer is not None:
                self._pending_timer.cancel()
            self._pending_timer = threading.Timer(_DEBOUNCE_DELAY_SEC, self._flush_pending)
            self._pending_timer.daemon = True
            self._pending_timer.start()

    def _flush_pending(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            except Exception:
                pass
        with self._debounce_lock:
            self._pending_timer = None

    # ------------------------------------------------------------------
    # Tracks
    # ------------------------------------------------------------------
    def upsert_track(
        self,
        *,
        audio_hash: str,
        path: str | Path,
        title: str,
        artist: str,
        duration_ms: int,
    ) -> int:
        """Insert atau update track. Return id track."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.execute("SELECT id FROM tracks WHERE audio_hash = ?", (audio_hash,))
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        """
                        INSERT INTO tracks
                          (audio_hash, path, title, artist, duration_ms, last_opened)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (audio_hash, str(path), title, artist, int(duration_ms), now),
                    )
                    rowid = cur.lastrowid
                    assert rowid is not None, "insert tracks gagal: lastrowid kosong"
                    track_id = int(rowid)
                else:
                    track_id = int(row[0])
                    cur.execute(
                        """
                        UPDATE tracks SET
                          path = ?, title = ?, artist = ?, duration_ms = ?, last_opened = ?
                        WHERE id = ?
                        """,
                        (str(path), title, artist, int(duration_ms), now, track_id),
                    )
            self._conn.commit()
            return track_id

    def get_track(self, audio_hash: str) -> dict[str, Any] | None:
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    "SELECT id, audio_hash, path, title, artist, duration_ms, last_opened "
                    "FROM tracks WHERE audio_hash = ?",
                    (audio_hash,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row, strict=True))

    # ------------------------------------------------------------------
    # Track settings
    # ------------------------------------------------------------------
    def save_track_settings(
        self,
        *,
        track_id: int,
        speed: float,
        volume: float,
        loop_mode: str | None = None,
        loop_a: int | None = None,
        loop_b: int | None = None,
        loop_after: str = "stop",
        repeat_count: int = 5,
        gap_ms: int = 0,
        preroll_ms: int = 0,
        ramp_json: str | None = None,
    ) -> None:
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """
                    INSERT INTO track_settings
                      (track_id, speed, volume, loop_mode, loop_a, loop_b,
                       loop_after, repeat_count, gap_ms, preroll_ms, ramp_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(track_id) DO UPDATE SET
                      speed=excluded.speed,
                      volume=excluded.volume,
                      loop_mode=excluded.loop_mode,
                      loop_a=excluded.loop_a,
                      loop_b=excluded.loop_b,
                      loop_after=excluded.loop_after,
                      repeat_count=excluded.repeat_count,
                      gap_ms=excluded.gap_ms,
                      preroll_ms=excluded.preroll_ms,
                      ramp_json=excluded.ramp_json
                    """,
                    (
                        track_id,
                        float(speed),
                        float(volume),
                        loop_mode,
                        loop_a,
                        loop_b,
                        str(loop_after or "stop"),
                        int(max(0, repeat_count)),
                        int(max(0, gap_ms)),
                        int(max(0, preroll_ms)),
                        ramp_json,
                    ),
                )
        self._schedule_flush()

    def load_track_settings(self, track_id: int) -> dict[str, Any]:
        """Return dict setting. Default jika belum ada."""
        defaults: dict[str, Any] = {
            "track_id": track_id,
            "speed": 1.0,
            "volume": 0.8,
            "loop_mode": None,
            "loop_a": None,
            "loop_b": None,
            "loop_after": "stop",
            "repeat_count": 5,
            "gap_ms": 0,
            "preroll_ms": 0,
            "ramp_json": None,
        }
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT track_id, speed, volume, loop_mode, loop_a, loop_b,
                           loop_after, repeat_count, gap_ms, preroll_ms, ramp_json
                    FROM track_settings WHERE track_id = ?
                    """,
                    (track_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return defaults
                cols = [d[0] for d in cur.description]
                data = dict(zip(cols, row, strict=True))
                defaults.update(data)
                return defaults

    # ------------------------------------------------------------------
    # Markers
    # ------------------------------------------------------------------
    def load_markers(self, track_id: int) -> list[Marker]:
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """
                    SELECT marker_uuid, time_ms, label, color, note
                    FROM markers WHERE track_id = ? ORDER BY time_ms ASC
                    """,
                    (track_id,),
                )
                rows = cur.fetchall()
        return [
            Marker(
                id=uuid if uuid else Marker.new_id(),
                time_ms=int(t),
                label=label or "",
                color=color or "#C43A31",
                note=note or "",
            )
            for (uuid, t, label, color, note) in rows
        ]

    def save_markers(self, track_id: int, markers: list[Marker]) -> None:
        """Simpan markers (REPLACE all existing markers untuk track_id ini)."""
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.execute("DELETE FROM markers WHERE track_id = ?", (track_id,))
                for m in markers:
                    cur.execute(
                        """
                        INSERT INTO markers (track_id, marker_uuid, time_ms, label, color, note)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            track_id,
                            m.id,
                            int(m.time_ms),
                            m.label or "",
                            m.color or "#C43A31",
                            m.note or "",
                        ),
                    )
        self._schedule_flush()

    def force_flush(self) -> None:
        """Paksa commit segera (dipanggil sebelum app exit)."""
        with self._debounce_lock:
            if self._pending_timer is not None:
                self._pending_timer.cancel()
                self._pending_timer = None
        with self._lock:
            try:
                self._conn.commit()
            except Exception:
                pass
