"""Fungsi bantu format dan parsing waktu.

Semua waktu internal menggunakan bilangan bulat milidetik (ms).
"""

from __future__ import annotations


def format_ms(ms: int, *, show_hours: bool = False) -> str:
    """Format milidetik menjadi string ``MM:SS.sss`` (atau ``HH:MM:SS.sss``).

    >>> format_ms(0)
    '00:00.000'
    >>> format_ms(42_350)
    '00:42.350'
    >>> format_ms(201_000, show_hours=True)
    '00:03:21.000'
    >>> format_ms(-1)
    Traceback (most recent call last):
      ...
    ValueError: ms tidak boleh negatif
    """
    if ms < 0:
        raise ValueError("ms tidak boleh negatif")
    total_seconds, millis = divmod(ms, 1000)
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if show_hours or hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def parse_hms(text: str) -> int:
    """Parsing string waktu (``H:M:S.ms`` / ``M:S.ms`` / ``S.ms``) menjadi ms.

    Mendukung variasi titik/koma untuk pemisah desimal dan titik dua untuk
    pemisah jam/menit/detik.

    >>> parse_hms("00:42.350")
    42350
    >>> parse_hms("3:21.0")
    201000
    >>> parse_hms("42")
    42000
    >>> parse_hms("abc")
    Traceback (most recent call last):
      ...
    ValueError: format waktu tidak dikenal: 'abc'
    """
    cleaned = text.strip().replace(",", ".")
    if not cleaned:
        raise ValueError("format waktu tidak dikenal: ''")
    # Tanda minus hanya diterima sebagai prefix keseluruhan.
    has_leading_minus = cleaned.startswith("-")
    abs_cleaned = cleaned[1:] if has_leading_minus else cleaned
    parts = abs_cleaned.split(":")
    # Tidak boleh ada minus tersembunyi di bagian tengah/desimal.
    for part in parts:
        if "-" in part:
            raise ValueError(f"waktu tidak boleh negatif: {text!r}")
    try:
        if len(parts) == 3:
            h, m, s = parts
            total = int(h) * 3600_000 + int(m) * 60_000 + _parse_seconds(s)
        elif len(parts) == 2:
            m, s = parts
            total = int(m) * 60_000 + _parse_seconds(s)
        elif len(parts) == 1:
            total = _parse_seconds(parts[0])
        else:
            raise ValueError(f"format waktu tidak dikenal: {text!r}")
    except ValueError:
        raise
    if has_leading_minus or total < 0:
        raise ValueError(f"waktu tidak boleh negatif: {text!r}")
    return total


def _parse_seconds(segment: str) -> int:
    """Parsing `segment` detik (bisa desimal) menjadi ms."""
    value = float(segment)
    if value < 0:
        raise ValueError(f"waktu tidak boleh negatif detik: {segment!r}")
    return int(round(value * 1000))
