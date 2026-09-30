"""Entry point aplikasi GuitarLoop Klasik.

Jalankan via:
    python -m guitarloop.app
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from guitarloop.core.audio_import import AudioImporter, check_ffmpeg_available
    from guitarloop.core.engine import MpvEngine
    from guitarloop.core.storage import Storage
    from guitarloop.ui.main_window import MainWindow
    from guitarloop.utils.i18n import t

    if argv is None:
        argv = sys.argv

    app = QApplication(list(argv))
    app.setApplicationName("GuitarLoop Klasik")
    app.setOrganizationName("GuitarLoop")

    # --- Pengecekan prasyarat ---
    startup_errors: list[str] = []
    if not check_ffmpeg_available():
        startup_errors.append(t("ffmpeg_not_found_msg"))

    try:
        import mpv  # noqa: F401  (hanya cek tersedia)
    except Exception as exc:  # noqa: BLE001
        startup_errors.append(
            "python-mpv tidak dapat mengimpor libmpv.\n"
            f"Alasan: {exc}\n\nPastikan mpv-2.dll (Windows) / libmpv.so / libmpv.dylib "
            "tersedia di PATH atau di folder yang sama dengan python.exe."
        )

    if startup_errors:
        QMessageBox.critical(
            None,
            t("app_title"),
            "Beberapa prasyarat tidak terpenuhi:\n\n" + "\n\n".join(startup_errors),
        )
        return 2

    # --- Instansiasi core ---
    engine = MpvEngine()
    storage = Storage()
    try:
        importer = AudioImporter()
    except RuntimeError as exc:
        QMessageBox.critical(None, t("app_title"), f"Tidak dapat membuat importer audio:\n{exc}")
        engine.shutdown()
        storage.close()
        return 3

    window = MainWindow(engine=engine, storage=storage, importer=importer)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
