"""Paksa hapus 3 file DB GuitarLoop (main + WAL + SHM)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

def main() -> int:
    # 100% sama dengan guitarloop.utils.paths.db_path()
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    base = appdata / "GuitarLoop"
    db_main = base / "guitarloop.db"
    db_wal = base / "guitarloop.db-wal"
    db_shm = base / "guitarloop.db-shm"

    print(f"Folder target: {base}")
    print(f"  exists: {base.exists()}")

    files = [db_main, db_wal, db_shm]
    deleted = 0
    errors = 0
    for p in files:
        if not p.exists():
            print(f"  ✅ {p.name}: sudah tidak ada")
            continue
        try:
            p.unlink()
            print(f"  🗑️  {p.name}: BERHASIL DIHAPUS (size={p.stat().st_size if False else '?'} bytes)")
            deleted += 1
        except PermissionError as e:
            print(f"  ❌ {p.name}: TIDAK BISA DIHAPUS (PermissionError).")
            print("     -> GuitarLoop app MASIH TERBUKA. Tutup app dulu, lalu run script LAGI.")
            errors += 1
        except OSError as e:
            print(f"  ❌ {p.name}: Error hapus: {e}")
            errors += 1

    if errors:
        print("\n⛔ ADA ERROR: Tutup GuitarLoop app, lalu jalankan `python _reset_db.py` LAGI.")
        return 2

    if deleted:
        print(f"\n✅ {deleted} file DB dihapus. Storage akan buat DB BARU schema V0.5 saat app start.")
    else:
        print("\n✅ Sudah bersih.")

    # ---- BONUS: Verifikasi storage.py SUDAH punya migration (diff sudah di-apply?) ----
    sfile = Path(__file__).parent / "guitarloop" / "core" / "storage.py"
    print(f"\n--- Verifikasi {sfile.name} ---")
    src = sfile.read_text(encoding="utf-8")
    has_mig = "migrations_track_settings" in src or "ALTER TABLE track_settings" in src
    if has_mig:
        print("  ✅ storage.py: punya kode MIGRATION (auto-handle DB lama kedepannya).")
    else:
        print("  ⚠️  storage.py: BELUM ada kode MIGRATION.")
        print("     (Bukan masalah SEKARANG karena DB baru dibuat dari nol.)")
        print("     Tapi di kemudian hari jika update versi baru tanpa reset DB,")
        print("     -> SILAKAN ACCEPT diff `storage.py` migration yang saya kirim sebelumnya ya.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())