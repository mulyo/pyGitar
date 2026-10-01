"""Tes impor audio TANPA GUI — untuk tahu di mana macet saat open file."""

from __future__ import annotations

import sys
from pathlib import Path

# Cek dependensi inti
print("=== 1. Import module core ===")
try:
    from guitarloop.core.audio_import import AudioImporter, check_ffmpeg_available
    from guitarloop.core.storage import Storage
    from guitarloop.utils.paths import ensure_dirs

    print("   ✅ Semua module core import OK")
except Exception:
    import traceback

    traceback.print_exc()
    sys.exit(1)

print("\n=== 2. Cek ffmpeg/ffprobe ===")
print(f"   check_ffmpeg_available() = {check_ffmpeg_available()}")

if not check_ffmpeg_available():
    print("   ❌ ffmpeg/ffprobe TIDAK ADA di PATH. Aplikasi tidak bisa impor audio.")
    print("   Solusi: copy ffmpeg.exe + ffprobe.exe ke .venv\\Scripts\\")
    sys.exit(2)

print("\n=== 3. Cari file MP3 pertama di project atau pilih dari args ===")
test_file: Path | None = None
if len(sys.argv) > 1:
    test_file = Path(sys.argv[1])
if test_file is None:
    # Coba cari mp3 secara acak jika ada
    candidates = list(Path.home().glob("Music/**/*.mp3"))[:3] + list(Path("c:/work").glob("*.mp3"))
    if candidates:
        test_file = candidates[0]
        print(f"   Auto-pilih file pertama: {test_file}")
    else:
        # File contoh tidak ada, minta user via input
        temp = (
            input("   Masukkan FULL PATH file MP3/WAV untuk tes (contoh: D:\\musik\\lagu.mp3): ")
            .strip()
            .strip('"')
        )
        if not temp:
            print("   ❌ Tidak ada file tes. Keluar.")
            sys.exit(3)
        test_file = Path(temp)

print(f"   File tes: {test_file}")
print(
    f"   File exists? {test_file.exists()}. Size={test_file.stat().st_size if test_file.exists() else 'N/A'} bytes"
)

if not test_file.exists():
    print("   ❌ File TIDAK ADA. Keluar.")
    sys.exit(4)

print("\n=== 4. Init AudioImporter & Storage ===")
try:
    ensure_dirs()
    importer = AudioImporter()
    storage = Storage()
    print(f"   ✅ importer & storage OK. DB di {storage._path}")  # noqa: SLF001
except Exception:
    import traceback

    traceback.print_exc()
    sys.exit(5)

print("\n=== 5. JALANKAN importer.import_file() ===")
print("   Progress real-time -> setiap progress event dicetak.")

last_phase = ""
last_ratio = -1.0


def _progress_cb(p):
    global last_phase, last_ratio
    pct = int(p.ratio * 100)
    tag = f"[{pct:>3d}%] {p.phase}"
    msg = f"{tag} — {p.message}" if p.message else tag
    if p.phase != last_phase or pct != last_ratio:
        print(f"   {msg}")
        last_phase = p.phase
        last_ratio = pct


try:
    result = importer.import_file(str(test_file), progress=_progress_cb)
except Exception:
    print("\n   ❌ IMPOR GAGAL (exception):")
    import traceback

    traceback.print_exc()
    sys.exit(6)

print("\n=== 6. RESULT ===")
print(f"   source_path      = {result.source_path}")
print(f"   wav_path (cache) = {result.wav_path}   [exists? {result.wav_path.exists()}]")
print(f"   audio_hash       = {result.audio_hash[:16]}...{result.audio_hash[-10:]}")
print(f"   duration_ms      = {result.duration_ms} ({result.duration_ms / 1000 / 60:.1f} menit)")
print(f"   sample_rate/ch   = {result.sample_rate} Hz / {result.channels} ch")
print(f"   title / artist   = {result.title!r} / {result.artist!r}")
print(f"   peaks levels     = {sorted(result.peaks.levels.keys())} ms")
print(
    "   shapes per level = "
    + ", ".join(f"{k}ms:{list(v.shape)}" for k, v in result.peaks.levels.items())
)

print("\n=== 7. TES Storage upsert_track + load_markers default ===")
tid = storage.upsert_track(
    audio_hash=result.audio_hash,
    path=result.source_path,
    title=result.title,
    artist=result.artist,
    duration_ms=result.duration_ms,
)
storage.force_flush()
print(f"   track_id = {tid}")
db_row = storage.get_track(result.audio_hash)
print(f"   get_track OK: id={db_row['id']}, title={db_row['title']!r}")
settings = storage.load_track_settings(tid)
print(
    f"   load_track_settings OK: speed={settings['speed']}, volume={settings['volume']}, repeat_count={settings['repeat_count']}"
)

print("\n\n🎉 ✅ SEMUA IMPOR + STORAGE BERHASIL. GUI harusnya bisa menampilkan waveform.")
print("   Jika core import sukses tetapi GUI MACET, masalah kemungkinan ada di:")
print("     a) PlayerEngine gagal load WAV cache (cek libmpv / mpv-2.dll)")
print("     b) Signal worker ke UI tidak terhubung (MainWindow import thread)")
storage.close()
print("\nBye.")
