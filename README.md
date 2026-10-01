# GuitarLoop Klasik — V0.5 (Markers & Loop Controller)

Aplikasi desktop Python untuk belajar gitar klasik dari rekaman MP3 dengan fitur
**loop berbasis penanda (marker)** dan perubahan kecepatan tanpa mengubah nada
(pitch-preserving time-stretch via `scaletempo2` libmpv).

## Status Versi

| Versi | Tanggal Rilis | Fokus | Lolos Quality Gate |
|---|---|---|---|
| **V0.1 Fondasi** | 2026-09 | Core engine + impor + waveform dasar + SQLite basic + i18n/hashing utils. | ✅ ruff 0 · mypy 0 · pytest 21/21 |
| **V0.5 Fase 2 (SAAT INI)** | 2026-09-30 | **Markers + Loop Controller** (tambah/geser/hapus penanda, 4 mode loop, persistensi penanda via audio_hash, counter loop selalu tampil, fixed ukuran jendela 640×360, TransportBar 2 baris). | ✅ ruff 0 · mypy 0 · pytest **52/52** |
| V1.0 MVP (berikutnya) | — | Speed ramp, jeda antar-ulangan, pre-roll, rantai loop, ekspor loop → MP3. | — |

## Daftar Isi Cepat
1. [Fitur Baru V0.5](#fitur-baru-v05-markers--loop)
2. [Arsitektur & Struktur Folder](#arsitektur--struktur-folder-terbaru)
3. [Asumsi Desain](#asumsi-desain-v01--tetap-berlaku-v05)
4. [Prasyarat](#prasyarat)
5. [Cara Menjalankan Aplikasi](#cara-menjalankan-aplikasi)
6. [Cara Menggunakan (Panduan Singkat User)](#panduan-singkat-penggunaan-v05)
7. [Pintasan Keyboard (Full V0.5)](#pintasan-keyboard-full-v05)
8. [Quality Gates & Pengujian](#quality-gates--pengujian)
9. [Uji Manual Verifikasi V0.5 (Kriteria Penerimaan)](#uji-manual-verifikasi-v05-5-langkah)

---

## Fitur Baru V0.5 (Markers & Loop)

### 📍 Sistem Penanda (§6.1 PRD)
- `M` = tambahkan penanda di posisi playhead sekarang.
- Daftar penanda kanan: klik untuk lompat, **F2** / double-click untuk rename, **Delete** untuk hapus.
- **Drag penanda di waveform** dengan mouse = geser posisi presisi.
- **Nudge keyboard** (geser penanda halus): `←/→` 10 ms, `Alt+←/→` 1 ms, `Shift+←/→` 100 ms.
- **Jarak minimum antar penanda = 50 ms** (menghindari tabrakan visual & loop bug).
- Auto-label `M1..Mn` urut waktu (rename manual = dipertahankan).

### 🔁 Sistem Loop (§6.2–6.3 PRD — 4 Mode)
| Mode | Tombol Pintasan | Keterangan |
|---|---|---|
| **A → B** | `[` = set A, `]` = set B | Custom 2 titik (tidak perlu marker). |
| **Bagian (Mn → Mn+1)** | `L` toggle | **Mode default.** Mainkan dari penanda ke penanda berikutnya secara berurutan. **Pilih penanda mana sebagai awal BAGIAN dari dropdown.** |
| **Awal → Penanda** | Dropdown saja | Mainkan dari 00:00.000 sampai penanda pilihan berhenti / wrap kembali ke 00:00. |
| **Penanda → Akhir** | Dropdown saja | Mainkan dari penanda pilihan sampai END OF TRACK lalu wrap ke penanda awal. |

Pengaturan loop:
- **Ulangan**: 1..99 atau **∞** (tak terbatas).
- **Selesai setelah selesai =** (a) **Berhenti di titik A** (kembali ke awal loop & pause), atau (b) **Lanjutkan playback** (deactivate loop & play normal sampai akhir).

### 📼 Counter Loop SELALU TERLIHAT (3 TEMPAT V0.5)
Tidak perlu lagi tebak "ini loop keberapa":
1. **Panel Loop (kiri atas)** = Counter BESAR 18pt warna: abu-abu (idle) → merah (sedang ulangan) → hijau stabilo (✅ SELESAI n x).
2. **Status Bar Permanen (kanan bawah jendela)** = `🔁 Loop: 2/5 (sisa 3)` berwarna sesuai state.
3. **Status Bar Flash (kiri bawah)** = counter terupdate tiap detik (flash 1500ms).
4. *(Debug opsional)* **Console PowerShell** = `[SOFTWARE-LOOP] 🔁 #2/5 OK: B(10xx) → A(5000)` untuk memverifikasi wrap.

### 💾 Persistensi & Perpindahan File (§6.5 PRD — Fitur Andalan)
- Penanda dan pengaturan loop disimpan di **SQLite `tracks`, `markers`, `track_settings`**.
- **Pengidentifikasi lagu = KONTEN HASH AUDIO** (bukan path file). Artinya:
  > ✅ **Anda BISA memindahkan, merename, atau menyalin file MP3/FLAC ke folder manapun.**
  > ✅ **Setelah dibuka ulang di app, SEMUA PENANDA & PENGATURAN LOOP MASIH TERBACA PERSIS.**
- **Debounce autosave 500 ms** (saat drag marker cepat → tidak thrash DB).
- **Force flush on close**: setiap penutupan app, commit 3x (markers, settings, storage global).

### 🖼️ Tampilan Jendela Baru V0.5
- **Ukuran tetap (fixed size)** = **640 × 360 px** (setengah dari 1280×720 V0.1, ringkas, fokus latihan).
- **TransportBar = 2 BARIS** (bukan 1 baris panjang V0.1):
  - **Baris 1 (atas)** = Back / Play / Pause / Stop / Forward + `MM:SS.sss time label` + **Seek Slider (full stretch)**.
  - **Baris 2 (bawah)** = Speed slider 0.25×–2.00× + Volume slider 0–100% (masing-masing setengah lebar bawah, mudah presisi).
- Layout **QDockWidget**: Kiri = Loop Panel, Kanan = Marker List Panel, Tengah = Waveform.

### ⚡ Teknis Implementasi Loop (Untuk Engineer)
Loop **100% di-handle via SOFTWARE FALLBACK seek manual** (bukan andalkan native `ab-loop-a`/`ab-loop-b` MPV wrapper) untuk menghindari variasi behaviour build `libmpv` Windows. Cara kerja:
1. User set bounds → engine menyimpan `_loop_bounds_ms = (a_ms, b_ms)`.
2. Setiap `QTimer` 33 Hz (30 FPS) → `MainWindow._on_poll()` memanggil `engine.poll()`.
3. Jika `pos >= b_ms + 4` → **engine.seek(a_ms)**, lalu panggil `LoopController.force_wrap_occurred()` (counter naik tepat 1x per wrap, TANPA double count).
4. Akurasi **< 33 ms** worst case (cukup untuk latihan gitar klasik di bawah JND manusia).

---

## Arsitektur & Struktur Folder (Terbaru V0.5)

Pemisahan bersih **Clean Architecture**: `core/` = TIDAK BOLEH import `PySide6` apapun. Satu-satunya titik temu = abstract `PlayerEngineListener` → wrapped jadi Qt Signal via `ui/qt_bridge.py`.

```
pyGitar/
├── guitarloop/
│   ├── app.py                      # Entry point: init engine/storage/window
│   │
│   ├── core/                       # 🔴 TIDAK BOLEH IMPORT PySide6 (pure domain logic)
│   │   ├── __init__.py             # Export publik: LoopMode, Marker, dll
│   │   ├── engine.py               # Abstract PlayerEngine + Real MpvEngine
│   │   ├── audio_import.py         # ffmpeg subprocess → WAV cache + peaks 3 level
│   │   ├── storage.py              # SQLite 3 tabel + WAL + debounce autosave
│   │   ├── markers.py              # Marker dataclass + MarkerCollection (CRUD+sorted+nudge)
│   │   └── loop_controller.py      # 4 mode state machine + iterasi finite/infinite
│   │
│   ├── ui/                         # 🟢 PySide6 GUI layer
│   │   ├── qt_bridge.py            # Terjemahkan PlayerEngineListener → Qt Signal
│   │   ├── shortcuts.py            # Daftar pintasan keyboard app-wide
│   │   ├── waveform_widget.py      # QWidget kustom: draw waveform + markers + loop area
│   │   ├── transport_bar.py        # Play/pause/stop + seek + speed/vol (2 BARIS V0.5)
│   │   ├── loop_panel.py           # Dock kiri: mode/AB/marker/repeat/counter BESAR
│   │   ├── marker_list.py          # Dock kanan: daftar penanda + edit/hapus inline
│   │   └── main_window.py          # Koordinator semua komponen (900+ baris)
│   │
│   ├── utils/
│   │   ├── timefmt.py              # `format_ms` + `parse_hms` strict
│   │   ├── hashing.py              # `compute_audio_hash` head+tail+size WAV SHA-256
│   │   ├── i18n.py                 # i18n dict Bahasa Indonesia (default)
│   │   └── paths.py                # app_data_dir + cache_dir + db_path
│   │
│   └── tests/
│       ├── test_timefmt.py         # (15 unit) format + parse HMS (strict negative)
│       ├── test_hashing.py         # (6 unit) hash audio deterministik
│       ├── test_markers.py         # (14 unit) add/rename/move/nudge/gap <50ms enforcement
│       ├── test_storage.py         # (10 unit) markers roundtrip, pindah file via hash OK
│       ├── test_loop_controller.py # (16 unit) state machine 4 mode, finite 5x lalu stop OK
│       └── test_loop_accuracy.py   # (3 parameterized) deviasi wrap < 10 ms ✅
│
├── _reset_db.py                    # (scratch opsional) paksa hapus 3 file DB (main+wal+shm)
├── _debug_import.py                # (scratch) tes AudioImporter+Storage TANPA GUI
├── _debug_engine.py                # (scratch) tes MpvEngine TANPA GUI
├── pyproject.toml                  # Ruff 100 col + mypy strict + pytest config
└── README.md                       # File ini (V0.5 terupdate)
```

---

## Asumsi Desain V0.1 (Tetap Berlaku V0.5)
1. **Cache path**:
   - Windows: `%APPDATA%\GuitarLoop\cache\`
   - Linux: `~/.cache/guitarloop/`
   - macOS: `~/Library/Caches/guitarloop/`
2. **Database path**: `<app_data>/guitarloop.db` (WAL mode + `threading.RLock` untuk thread-safety).
3. **Waveform peaks**: 3 level resolusi bucket (1000 ms, 100 ms, 10 ms) disimpan `.npy`. Level dipilih otomatis sesuai zoom.
4. **Time-stretch default**: `scaletempo2` via mpv (kualitas cukup untuk 0.25×–2.0× latihan).
5. **Audio hash**: SHA-256 atas 4 blok pertama & terakhir @64KB WAV cache + ukuran total 8-byte prefix.
6. **Polling posisi**: QTimer **30 Hz** (33,3 ms per tick) untuk posisi + counter wrap.

---

## Prasyarat

| Komponen | Versi minimum | Keterangan Instalasi Windows |
|---|---|---|
| Python | 3.11+ | 64-bit (Wajib! `PySide6 6.6+` butuh 64-bit). |
| `ffmpeg.exe` + `ffprobe.exe` | 5.0+ | Copy ke `.venv\Scripts\` (otomatis PATH). Verifikasi: `ffmpeg -version`. |
| `libmpv` (Windows SHARED build) | 0.36+ | Download **shinchiro libmpv** atau **mpv.net** build → ekstrak **`mpv-2.dll`** → copy ke `.venv\Scripts\`. Verifikasi: `python -c "import mpv; p=mpv.MPV(vo='null',video=False); print(p.mpv_version); p.terminate()"` → cetak versi = sukses. |

---

## Cara Menjalankan Aplikasi

```powershell
# 1. Masuk folder project (gunakan PowerShell / CMD)
cd c:\work\pyGitar

# 2. Aktifkan virtual environment
.venv\Scripts\Activate.ps1
# Jika Execution Policy error:
#   Set-ExecutionPolicy -Scope Process Bypass
# Atau pakai CMD: .venv\Scripts\activate.bat

# 3. Install dependencies (jika pertama kali)
pip install -e ".[dev]"

# 4. Jalankan app! 🎸
python -m guitarloop.app
```

---

## Panduan Singkat Penggunaan V0.5

1. **File → Buka file audio** (MP3 / FLAC / WAV / OGG / format didukung ffmpeg). Tunggu ~1–2 dtk impor pertama.
2. **Mainkan (Space atau Play di TransportBar)**, dan **tandai 2+ titik penting** dengan **tombol `M`** saat playhead di posisi yang diinginkan.
3. **Panel Loop kiri**:
   - ✅ **Centang** `✅ Aktifkan Pengulangan`.
   - Pilih **Mode = Bagian (Mn → Mn+1)**.
   - **Pilih Penanda = M1** (maka bagian = M1 → M2).
   - Isi **Ulangan = 5** (hilangkan ceklist ∞).
   - Pilih **Selesai = Berhenti di A**.
4. Tekan **Space** untuk mulai play dari sekitar 1 detik sebelum M1.
5. ✅ **Amati Counter Loop** (merah) → naik bertahap `1/5 → 2/5 → 3/5 → 4/5 → 5/5`.
6. Setelah selesai → Counter berubah jadi **HIJAU** `✅ SELESAI 5x ulangan` → playback berhenti.
7. Tutup app → buka ulang file yang sama → **semua penanda + pengaturan loop PULIH**.
8. Coba **RENAME / PINDAHKAN file MP3** ke folder lain → buka ulang file yang sudah dipindah → **penanda DAN settings TERBACA LAGI** (keajaiban konten audio hash!).

---

## Pintasan Keyboard (Full V0.5)

| Kategori | Tombol | Aksi |
|---|---|---|
| **Playback** | `Space` | Toggle Play / Pause |
| | `S` atau `Stop` | Berhenti & kembali ke 0 |
| **Seek** | `←` / `→` | mundur / maju 1 detik |
| | `Ctrl + ←` / `Ctrl + →` | mundur / maju 5 detik |
| | `J` / `K` | mundur / maju 10 detik |
| **Kecepatan** | `↑` / `↓` | ±5% speed (0.25×–2.0×) |
| | `R` | Reset speed ke 1.00× |
| **Volume** | `,` / `.` | ±5% volume |
| **Zoom Waveform** | `Ctrl + Plus (+)` | zoom in (fokus detail) |
| | `Ctrl + Minus (-)` | zoom out (lihat keseluruhan) |
| | `Ctrl + 0` | reset zoom (fit full duration) |
| **🔖 Penanda Baru** | **`M`** | ➕ Tambah penanda di playhead sekarang (jarak min 50 ms) |
| | Double-click waveform | Tambah penanda di klik |
| **Edit Penanda (terpilih)** | `Delete` / `Backspace` | Hapus penanda terpilih |
| | `F2` | Rename inline di panel Marker List kanan |
| | `←` / `→` (setelah klik penanda) | **Nudge ±10 ms** |
| | `Alt + ←/→` | Nudge ±1 ms (presisi tinggi!) |
| | `Shift + ←/→` | Nudge ±100 ms (cepat) |
| **🔁 Loop** | **`L`** | On / off toggle pengulangan |
| | `[` | **Set titik A** (mode A→B) = posisi playhead sekarang |
| | `]` | **Set titik B** (mode A→B) = posisi playhead sekarang |
| **File** | `Ctrl + O` | Buka file audio baru |
| | `Ctrl + Q` / `Alt + F4` | Tutup aplikasi (auto flush DB) |

---

## Quality Gates & Pengujian

JALANKAN 4 PERINTAH INI SEBELUM SETIAP COMMIT / SEBELUM UPDATE FITUR BARU:

```powershell
# 1. Lint & style (aturan 100 kolom, strict UP/F/... )
ruff check guitarloop
# (auto-fix 90% kasus jika ada error:
ruff check --fix --unsafe-fixes guitarloop && ruff format guitarloop

# 2. Type Check (mypy strict = true).
mypy guitarloop

# 3. Jalankan SEMUA 52 unit test (V0.1 + V0.5) — HARUS 100% LULUS.
pytest guitarloop/tests -q
# Output seharusnya:
#   52 passed, 1 warning in 4.92s

# (Opsional debug non-GUI untuk diagnose masalah impor/engine)
python -u _debug_import.py  "C:\path\ke\file_audio.mp3"
python -u _debug_engine.py "C:\path\ke\cache\<HASH>.wav"

# (Opsional reset DB jika terjadi schema mismatch upgrade versi)
python _reset_db.py
```

---

## Uji Manual Verifikasi V0.5 (5 Langkah)

**Ini adalah kriteria penerimaan Fase 2. Semua 5 harus PASS.**

| # | Skenario | Ekspektasi | Status |
|---|---|---|---|
| 1 | **Buat 4 penanda**: tekan `M` x4 di 4 posisi berbeda, rename 1 via `F2`, drag 1 marker dengan mouse. | Penanda tampil M1..M4, label rename terlihat, hasil drag tersimpan & autosave. | — |
| 2 | **Loop bagian 5x lalu berhenti**: Aktifkan loop → mode Bagian → pilih M1 → ulangan 5 → play dari sebelum M1. | Counter n/5 **bertambah PERSIS 1 per wrap**. Setelah wrap ke-5 → counter hijau `✅ SELESAI 5x ulangan` & **playback BERHENTI** otomatis. | — |
| 3 | **Tutup app → buka ulang file yang SAMA.** | 4 penanda + semua pengaturan loop (mode, repeat count, speed volume) **PULIH PERSIS**. | — |
| 4 | **Rename / Pindahkan file audio** ke folder lain. Buka file yang sudah DIPINDAHKAN. | **4 penanda MASIH ADA & settings loop tetap sama!** (buktinya persistensi via hash audio BUKAN path). | — |
| 5 | **Hanya pakai KEYBOARD** (tanpa klik mouse apapun): M x4, Delete 1, [ & ] set A/B, L toggle loop, Space play sampai selesai. | Semua aksi bisa dilakukan tanpa mouse = akses keyboard lengkap. | — |

---

## Catatan Rilis V0.5 Penting untuk Maintainer
1. Build `libmpv` Windows SHARED (mpv-2.dll) tertentu **tidak reliable** pada property native `ab-loop-a/b` (TypeError invalid value). Oleh karena itu V0.5 sengaja **100% nonaktifkan native loop** dan pakai software seek manual di `_on_poll` 33 Hz. Jika nanti upgrade libmpv yang fix, bisa aktifkan kembali di `core/engine.py:set_loop()` (ada placeholder read-back verifikasi).
2. Schema `track_settings` punya kolom `loop_after` baru. Untuk user yang punya DB lama V0.1 sebelum upgrade, storage.py **auto-migrate ALTER TABLE ADD COLUMN** dengan exception handling. Sebaiknya jalankan `python _reset_db.py` jika upgrade lintas major.
3. Minimum QApplication width 640 px. Jika suatu saat butuh responsive layout, cukup ganti `setFixedSize(640, 360)` → `setMinimumSize(640, 420)` di `main_window.py:_build_ui()`.

---

*Dokumen ini terakhir diperbarui: V0.5 — 2026-10-01.*