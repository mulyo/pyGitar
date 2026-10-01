# GuitarLoop Klasik — V0.1 (Fondasi)

Aplikasi desktop Python untuk belajar gitar klasik dari rekaman MP3 dengan fitur
loop berbasis penanda dan perubahan kecepatan tanpa mengubah nada.

## V0.1 — Cakupan
- Struktur paket `guitarloop/` dengan pemisahan `core/` ↔ `ui/`
- Impor audio via ffmpeg/ffprobe → decode ke WAV PCM 16-bit cache lokal
- Metadata via ffprobe (durasi, sample rate, title, artist)
- Waveform peaks (3 level resolusi) disimpan sebagai `.npy`
- `PlayerEngine` abstrak + implementasi `MpvEngine` (libmpv)
- Playback dasar: load, play, pause, stop, seek, set_speed (0.25×–2.0×), set_volume
- Pitch correction aktif via `audio-pitch-correction=yes`
- Widget waveform kustom (QPainter) dengan playhead & zoom
- Transport bar (play/pause/stop + slider kecepatan)
- SQLite (tabel `tracks` + `track_settings` dasar)
- Hashing audio (SHA-256 sebagian isi + ukuran file)
- Pintasan keyboard dasar (Space, ←/→, ↑/↓, Ctrl+O, +/-)
- Type hints lengkap, ruff + mypy + pytest

## Asumsi Desain (diverifikasi sederhana)
1. **Cache path**:
   - Windows: `%APPDATA%\GuitarLoop\cache\`
   - Linux: `~/.cache/guitarloop/`
   - macOS: `~/Library/Caches/guitarloop/`
2. **Database path**: `<app_data>/guitarloop.db`
3. **Waveform peaks**: 3 level resolusi bucket (1000 ms, 100 ms, 10 ms)
   disimpan sebagai numpy array `.npy` di cache. Level dipilih otomatis
   berdasarkan faktor zoom.
4. **Time-stretch default**: scaletempo2 via mpv (kualitas cukup untuk 0.25×–2.0×).
5. **Audio hash**: SHA-256 atas 4 blok pertama & terakhir 64 KB file WAV cache
   + ukuran total file WAV. Hash ini menjadi kunci unik lagu terlepas dari
   path/nama asli MP3.
6. **Polling posisi**: posisi playback dipoll via `QTimer` 30 Hz (bukan observer
   mpv native) agar interface PySide6 tetap bersih dari callback native mpv
   yang berjalan di thread terpisah.

## Prasyarat
- Python 3.11+
- `ffmpeg` dan `ffprobe` di `PATH` (atau di folder `bin/` proyek)
- `libmpv` (Windows: `mpv-2.dll`; Linux: `libmpv.so`; macOS: `libmpv.dylib`)
  tersedia di PATH atau di folder yang sama dengan eksekusi Python.

## Cara Menjalankan
```cmd
cd c:\work\pyGitar
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m guitarloop.app
ruff check guitarloop
ruff format --check guitarloop
mypy guitarloop
pytest guitarloop/tests -v

## Cara Menjalankan Hanya Pengujian Unit (tanpa GUI)
```cmd
pytest guitarloop/tests/test_timefmt.py guitarloop/tests/test_hashing.py -v
undefined


debug import audio 
python -u _debug_import.py "C:\Users\msa\Downloads\YuE2_00004.flac"

python -u _debug_engine.py "C:\Users\msa\Downloads\YuE2_00004.flac"