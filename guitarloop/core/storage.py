"""Penyimpanan persisten SQLite.

Untuk V0.1: tabel `tracks` dan `track_settings` (untuk restore speed/volume
per lagu). Tabel markers dan practice_log ditambahkan di V0.5.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

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

CREATE TABLE IF NOT EXISTS track_settings (
  track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
  speed REAL NOT NULL DEFAULT 1.0,
  volume REAL NOT NULL DEFAULT 0.8,
  loop_mode TEXT,
  loop_a INTEGER,
  loop_b INTEGER,
  repeat_count INTEGER NOT NULL DEFAULT 5,
  gap_ms INTEGER NOT NULL DEFAULT 0,
  preroll_ms INTEGER NOT NULL DEFAULT 0,
  ramp_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_tracks_last_opened ON tracks(last_opened);
"""


class Storage:
    """Wrapper SQLite thread-safe."""

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
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

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
    ) -> None:
        with self._lock:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """
                    INSERT INTO track_settings (track_id, speed, volume)
                    VALUES (?, ?, ?)
                    ON CONFLICT(track_id) DO UPDATE SET speed=excluded.speed, volume=excluded.volume
                    """,
                    (track_id, float(speed), float(volume)),
                )
            self._conn.commit()

    def load_track_settings(self, track_id: int) -> dict[str, Any]:
        """Return dict setting. Default jika belum ada."""
        defaults = {
            "track_id": track_id,
            "speed": 1.0,
            "volume": 0.8,
            "loop_mode": None,
            "loop_a": None,
            "loop_b": None,
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
                           repeat_count, gap_ms, preroll_ms, ramp_json
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
