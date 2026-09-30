"""Pusat string terjemahan agar mudah dilokalisasi nanti.

Untuk V0.1 hanya Bahasa Indonesia. Untuk menambah bahasa baru: buat dict
translation baru dan ganti `_LANG` sesuai konfigurasi pengguna.
"""

from __future__ import annotations

_STRINGS: dict[str, dict[str, str]] = {
    "id": {
        # --- Main / App ---
        "app_title": "GuitarLoop Klasik",
        "app_title_with_file": "GuitarLoop Klasik — {title}",
        "menu_file": "&File",
        "menu_edit": "&Edit",
        "menu_view": "&Tampilan",
        "menu_help": "&Bantuan",
        "action_open": "&Buka file audio...",
        "action_quit": "&Keluar",
        "action_zoom_in": "Perbesar &waveform",
        "action_zoom_out": "Perkecil wa&veform",
        "action_about": "&Tentang",
        "shortcuts_title": "Pintasan Keyboard",
        # --- File dialog ---
        "open_dialog_title": "Pilih file audio",
        "open_dialog_filter": ("File audio (*.mp3 *.wav *.flac *.m4a *.ogg);;Semua file (*.*)"),
        "no_file_chosen": "Tidak ada file yang dipilih.",
        "import_in_progress": "Mengimpor: {name}...",
        "import_done": "Selesai mengimpor: {title}",
        "import_error_title": "Gagal mengimpor",
        "import_error_msg": "Tidak dapat memproses file:\n{path}\n\nAlasan: {reason}",
        "ffmpeg_not_found_title": "ffmpeg tidak tersedia",
        "ffmpeg_not_found_msg": (
            "Pastikan ffmpeg dan ffprobe ada di PATH atau di folder bin/.\n"
            "Aplikasi tidak dapat mengimpor audio tanpa keduanya."
        ),
        # --- Transport bar ---
        "btn_play": "▶ Mainkan",
        "btn_pause": "⏸ Jeda",
        "btn_stop": "⏹ Berhenti",
        "btn_seek_back": "⏮ -5 dtk",
        "btn_seek_fwd": "⏭ +5 dtk",
        "lbl_speed": "Kecepatan:",
        "lbl_volume": "Volume:",
        "time_format": "{pos} / {dur}",
        "not_loaded": "--:--.--- / --:--.---",
        # --- Waveform ---
        "waveform_empty": "Seret file audio atau gunakan File → Buka",
        "waveform_loading": "Menghitung waveform...",
        # --- Messages ---
        "about_title": "Tentang GuitarLoop Klasik",
        "about_body": (
            "GuitarLoop Klasik v{version}\n\n"
            "Alat latihan gitar klasik berbasis loop.\n"
            "Fitur V0.1: impor audio, playback, speed shift, waveform."
        ),
        "err_file_too_short": "File terlalu pendek untuk diputar (<250 ms).",
        "err_format_unsupported": "Format audio tidak didukung atau file rusak.",
    }
}

_LANG = "id"


def t(key: str, **kwargs: object) -> str:
    """Ambil string terjemahan. Key tidak ditemukan → return key itu sendiri."""
    table = _STRINGS.get(_LANG, {})
    value = table.get(key, key)
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value


def set_lang(lang: str) -> None:
    """(Untuk penggunaan mendatang) ganti bahasa aktif."""
    global _LANG
    if lang in _STRINGS:
        _LANG = lang
