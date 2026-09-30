"""Perhitungan hash identitas audio.

Hash dihitung dari **file WAV cache** (bukan MP3 asli) supaya identik untuk
sumber audio yang sama meskipun dikodekan ulang dengan encoder MP3 berbeda.

Strategi: ambil 4 blok pertama + 4 blok terakhir (masing-masing 64 KB) ditambah
ukuran file total. Cukup unik untuk lagu berbeda dan cepat dihitung untuk
file 60 menit sekalipun.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_BLOCK_SIZE = 64 * 1024  # 64 KB
_HEAD_TAIL_BLOCKS = 4


def compute_audio_hash(wav_path: str | Path) -> str:
    """Return string heksadesimal SHA-256 identitas dari file WAV.

    Parameters
    ----------
    wav_path:
        Path ke file WAV PCM cache.

    Raises
    ------
    FileNotFoundError
        Jika file tidak ada.
    ValueError
        Jika file terlalu kecil (< 1 KB).
    """
    path = Path(wav_path)
    if not path.is_file():
        raise FileNotFoundError(f"file WAV tidak ditemukan: {path}")
    size = path.stat().st_size
    if size < 1024:
        raise ValueError(f"file WAV terlalu kecil (<1 KB): {size} bytes")

    hasher = hashlib.sha256()
    hasher.update(size.to_bytes(8, byteorder="big", signed=False))

    with path.open("rb") as fh:
        # Blok pertama
        for _ in range(_HEAD_TAIL_BLOCKS):
            chunk = fh.read(_BLOCK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)

        # Blok terakhir (hanya jika ukuran cukup)
        tail_offset = max(0, size - _BLOCK_SIZE * _HEAD_TAIL_BLOCKS)
        fh.seek(tail_offset)
        remaining = size - tail_offset
        while remaining > 0:
            n = min(_BLOCK_SIZE, remaining)
            chunk = fh.read(n)
            if not chunk:
                break
            hasher.update(chunk)
            remaining -= len(chunk)

    return hasher.hexdigest()
