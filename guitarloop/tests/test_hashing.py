from pathlib import Path

import pytest

from guitarloop.utils.hashing import compute_audio_hash


def _make_dummy_wav(tmp_path: Path, size_kb: int, *, seed: int = 0) -> Path:
    """Buat file WAV pseudo (header + noise sampel) untuk test hash."""
    import struct

    # Header WAV PCM 16-bit mono 44100 Hz minimal.
    p = tmp_path / f"dummy_{seed}_{size_kb}kb.wav"
    data_size = max(64, size_kb * 1024 - 44)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        44100,
        44100 * 2,
        2,
        16,
        b"data",
        data_size,
    )
    assert len(header) == 44
    rng_state = seed
    body = bytearray()
    for _i in range(data_size):
        # Linear congruential untuk byte deterministik per seed
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        body.append(rng_state & 0xFF)
    with p.open("wb") as fh:
        fh.write(header)
        fh.write(bytes(body))
    return p


class TestComputeAudioHash:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            compute_audio_hash(tmp_path / "nope.wav")

    def test_tiny_file_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "tiny.wav"
        p.write_bytes(b"\x00" * 500)
        with pytest.raises(ValueError, match="terlalu kecil"):
            compute_audio_hash(p)

    def test_deterministic(self, tmp_path: Path) -> None:
        a = _make_dummy_wav(tmp_path, 512, seed=7)
        b = _make_dummy_wav(tmp_path, 512, seed=7)
        assert compute_audio_hash(a) == compute_audio_hash(b)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        a = _make_dummy_wav(tmp_path, 512, seed=1)
        b = _make_dummy_wav(tmp_path, 512, seed=2)
        assert compute_audio_hash(a) != compute_audio_hash(b)

    def test_different_size_different_hash(self, tmp_path: Path) -> None:
        a = _make_dummy_wav(tmp_path, 256, seed=3)
        b = _make_dummy_wav(tmp_path, 512, seed=3)
        assert compute_audio_hash(a) != compute_audio_hash(b)

    def test_hash_is_64_hex_chars(self, tmp_path: Path) -> None:
        p = _make_dummy_wav(tmp_path, 1024, seed=0)
        h = compute_audio_hash(p)
        assert len(h) == 64
        int(h, 16)  # harus valid heksadesimal
