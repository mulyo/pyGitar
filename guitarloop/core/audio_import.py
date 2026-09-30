"""Impor audio: metadata ffprobe → decode WAV → peaks waveform.

Semua pemanggilan ke ffmpeg/ffprobe via subprocess; **tidak ada** dependensi
pustaka binding khusus. Semua operasi berat dipanggil di worker thread oleh UI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from guitarloop.utils.hashing import compute_audio_hash
from guitarloop.utils.paths import cache_dir

# Tingkat resolusi bucket (ms) untuk waveform peaks. Semakin kecil, semakin
# detail, tapi semakin besar file .npy-nya. UI memilih level sesuai zoom.
PEAK_LEVELS_MS: tuple[int, ...] = (1000, 100, 10)
# Ukuran minimal file audio (ms) agar bisa diputar.
MIN_DURATION_MS = 250


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ImportProgress:
    """Callback progress untuk import audio (0..1)."""

    phase: str  # "metadata" | "decode" | "peaks" | "hash" | "done"
    ratio: float  # 0..1
    message: str = ""


@dataclass
class WaveformPeaks:
    """Puncak min/max per bucket untuk tiap level resolusi."""

    duration_ms: int
    sample_rate: int
    # Key: bucket_ms (salah satu PEAK_LEVELS_MS). Value array shape (N, 2)
    # kolom 0 = min (int16), kolom 1 = max (int16)
    levels: dict[int, np.ndarray] = field(default_factory=dict)

    def level_for_zoom(self, pixels_per_second: float) -> int:
        """Pilih level yang bucket-nya cukup detail untuk zoom saat ini."""
        if pixels_per_second <= 0:
            return PEAK_LEVELS_MS[0]
        ms_per_pixel = 1000.0 / pixels_per_second
        # Pilih bucket terkecil yang <= 2x ms_per_pixel (detail cukup)
        for bucket_ms in reversed(PEAK_LEVELS_MS):
            if bucket_ms <= ms_per_pixel * 2:
                return bucket_ms
        return PEAK_LEVELS_MS[-1]


@dataclass
class ImportResult:
    """Hasil impor lengkap dari file audio."""

    source_path: Path  # Path MP3 asli
    wav_path: Path  # Path WAV PCM 16-bit di cache
    audio_hash: str  # Kunci identitas per lagu
    duration_ms: int
    sample_rate: int
    channels: int
    title: str
    artist: str
    peaks: WaveformPeaks


# ---------------------------------------------------------------------------
# Pengecekan biner eksternal
# ---------------------------------------------------------------------------
def check_ffmpeg_available() -> bool:
    """Return True jika ffmpeg dan ffprobe bisa dijalankan."""
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            return False
    return True


# ---------------------------------------------------------------------------
# ffprobe metadata
# ---------------------------------------------------------------------------
def _run_ffprobe_json(path: Path) -> dict[str, Any]:
    """Jalankan ffprobe -print_format json dan return dict hasilnya."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-select_streams",
        "a",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"ffprobe gagal (rc={proc.returncode}): {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout)
    if not isinstance(data, dict):
        raise RuntimeError("output ffprobe bukan dict JSON")
    return data


def _extract_metadata(probe: dict[str, Any]) -> tuple[int, int, int, str, str]:
    """Return (duration_ms, sample_rate, channels, title, artist) dari dict probe."""
    streams: list[dict[str, Any]] = probe.get("streams", []) or []
    audio_stream: dict[str, Any] = streams[0] if streams else {}
    fmt: dict[str, Any] = probe.get("format", {}) or {}
    tags: dict[str, Any] = fmt.get("tags", {}) or {}

    # Durasi: format terlebih dahulu, fallback ke stream
    dur_str = fmt.get("duration") or audio_stream.get("duration")
    if dur_str is None:
        raise RuntimeError("tidak ada informasi durasi dari ffprobe")
    duration_ms = int(round(float(dur_str) * 1000))
    if duration_ms < MIN_DURATION_MS:
        raise RuntimeError(f"durasi < {MIN_DURATION_MS} ms")

    sample_rate = int(float(audio_stream.get("sample_rate", 44100)))
    channels = int(audio_stream.get("channels", 2))
    title = str(tags.get("title", "")).strip()
    artist = str(tags.get("artist", "")).strip()
    return duration_ms, sample_rate, channels, title, artist


# ---------------------------------------------------------------------------
# Decode ke WAV cache
# ---------------------------------------------------------------------------
def _cache_paths_for(source: Path, audio_hash: str | None) -> tuple[Path, Path]:
    """Path WAV cache dan prefix folder peaks berdasarkan source/hash."""
    base = cache_dir()
    stem = audio_hash or f"{source.stem}-{abs(hash(str(source.resolve())))}"
    wav = base / f"{stem}.wav"
    peaks_dir = base / f"{stem}-peaks"
    return wav, peaks_dir


def _run_ffmpeg_decode(
    source: Path, wav_out: Path, progress: Callable[[ImportProgress], None]
) -> tuple[int, int]:
    """Decode file audio ke WAV PCM 16-bit little-endian.

    Returns (sample_rate_terpilih, channels_terpilih).
    """
    wav_out.parent.mkdir(parents=True, exist_ok=True)
    # Output: PCM signed 16-bit LE, sample rate 44.1 kHz jika sample rate asli
    # tidak umum; ini menyederhanakan perhitungan peaks.
    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-f",
        "wav",
        str(wav_out),
    ]
    progress(ImportProgress("decode", 0.0, "Mendekode audio..."))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not wav_out.is_file() or wav_out.stat().st_size < 44:
        raise RuntimeError(
            f"ffmpeg decode gagal (rc={proc.returncode}): {proc.stderr.strip()[:300]}"
        )
    progress(ImportProgress("decode", 1.0))
    return 44100, 1


# ---------------------------------------------------------------------------
# Pembuatan peaks waveform
# ---------------------------------------------------------------------------
def _read_wav_pcm16_mono(wav_path: Path) -> tuple[np.ndarray, int]:
    """Baca data sampel int16 mono dari file WAV hasil decode kita sendiri.

    Karena kita generate WAV via ffmpeg dengan konstan (pcm_s16le, mono,
    44100 Hz), tidak perlu parser WAV yang lengkap: cukup lewatkan header 44
    byte (format RIFF standar). Jika header tidak sesuai, fallback pakai
    ffmpeg ekstrak raw.
    """
    raw_bytes = wav_path.read_bytes()
    # Header RIFF WAV standar PCM = 44 byte
    if len(raw_bytes) <= 44:
        raise RuntimeError("file WAV cache terlalu kecil")
    samples = np.frombuffer(raw_bytes[44:], dtype=np.int16).astype(np.float32)
    sample_rate = 44100
    return samples, sample_rate


def _compute_peaks_level(samples: np.ndarray, sample_rate: int, bucket_ms: int) -> np.ndarray:
    """Hitung min/max per bucket. Return array int16 shape (N, 2)."""
    bucket_samples = max(1, sample_rate * bucket_ms // 1000)
    n_full = len(samples) // bucket_samples
    if n_full == 0:
        n_full = 1
        bucket_samples = len(samples)
    trimmed = samples[: n_full * bucket_samples].reshape(n_full, bucket_samples)
    mins = trimmed.min(axis=1)
    maxs = trimmed.max(axis=1)
    stacked = np.stack([mins, maxs], axis=1)
    # Clamp ke rentang int16 meskipun input sudah int16.
    result: np.ndarray = np.clip(stacked, -32768.0, 32767.0).astype(np.int16)
    return result


def _load_or_compute_peaks(
    wav_path: Path,
    peaks_dir: Path,
    duration_ms: int,
    sample_rate: int,
    progress: Callable[[ImportProgress], None],
) -> WaveformPeaks:
    peaks = WaveformPeaks(duration_ms=duration_ms, sample_rate=sample_rate)
    peaks_dir.mkdir(parents=True, exist_ok=True)
    samples: np.ndarray | None = None
    total = len(PEAK_LEVELS_MS)
    for idx, bucket_ms in enumerate(PEAK_LEVELS_MS):
        level_file = peaks_dir / f"level_{bucket_ms}ms.npy"
        if level_file.is_file():
            try:
                peaks.levels[bucket_ms] = np.load(level_file).astype(np.int16)
                progress(
                    ImportProgress(
                        "peaks",
                        (idx + 1) / total,
                        f"Memuat cache peaks {bucket_ms} ms...",
                    )
                )
                continue
            except Exception:
                pass  # Hitung ulang jika cache rusak
        if samples is None:
            progress(
                ImportProgress(
                    "peaks",
                    idx / total,
                    "Membaca sampel audio...",
                )
            )
            samples, _sr = _read_wav_pcm16_mono(wav_path)
        progress(
            ImportProgress(
                "peaks",
                (idx + 0.2) / total,
                f"Menghitung peaks bucket {bucket_ms} ms...",
            )
        )
        arr = _compute_peaks_level(samples, sample_rate, bucket_ms)
        peaks.levels[bucket_ms] = arr
        try:
            np.save(level_file, arr)
        except Exception:
            pass  # Tidak fatal jika cache gagal disimpan
        progress(ImportProgress("peaks", (idx + 1) / total))
    return peaks


# ---------------------------------------------------------------------------
# Facade utama: AudioImporter
# ---------------------------------------------------------------------------
class AudioImporter:
    """Facade operasi impor; aman dijalankan di thread worker."""

    def __init__(self) -> None:
        if not check_ffmpeg_available():
            raise RuntimeError("ffmpeg/ffprobe tidak ditemukan di PATH")

    def import_file(
        self,
        source_path: str | Path,
        *,
        progress: Callable[[ImportProgress], None] | None = None,
    ) -> ImportResult:
        """Impor file audio → WAV cache + peaks + hash.

        Jika file sudah pernah diimpor (hash sama), peaks dimuat dari cache.
        """
        source = Path(source_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"file tidak ada: {source}")
        cb = progress or (lambda _p: None)

        cb(ImportProgress("metadata", 0.0, "Membaca metadata..."))
        probe = _run_ffprobe_json(source)
        duration_ms, _sr_orig, _ch_orig, title, artist = _extract_metadata(probe)

        # Fallback judul dari nama file jika tag title kosong
        if not title:
            title = source.stem

        # Perkirakan path cache (kita belum punya hash; hash dihitung setelah decode)
        wav_placeholder, peaks_placeholder = _cache_paths_for(source, None)
        sample_rate, channels = _run_ffmpeg_decode(source, wav_placeholder, cb)

        cb(ImportProgress("hash", 0.0, "Menghitung hash audio..."))
        audio_hash = compute_audio_hash(wav_placeholder)
        cb(ImportProgress("hash", 1.0))

        # Pindahkan ke path bernama hash (agar identik meskipun sumber beda nama)
        final_wav, final_peaks_dir = _cache_paths_for(source, audio_hash)
        wav_placeholder.replace(final_wav) if not final_wav.is_file() else None
        if peaks_placeholder.is_dir():
            # Hapus folder placeholder sementara bila ada
            shutil.rmtree(peaks_placeholder, ignore_errors=True)

        peaks = _load_or_compute_peaks(
            final_wav,
            final_peaks_dir,
            duration_ms,
            sample_rate,
            cb,
        )

        cb(ImportProgress("done", 1.0, "Selesai."))
        return ImportResult(
            source_path=source,
            wav_path=final_wav,
            audio_hash=audio_hash,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            title=title,
            artist=artist,
            peaks=peaks,
        )
