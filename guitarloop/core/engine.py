"""Abstraksi PlayerEngine + implementasi libmpv.

Core layer TIDAK boleh import PySide6. Sinyal dikirim lewat listener callback
sederhana; lapisan UI (`ui/main_window.py`) yang akan meneruskannya ke Qt Signal.
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass
from pathlib import Path


class PlayerState(enum.Enum):
    IDLE = "idle"
    LOADED = "loaded"
    PLAYING = "playing"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class LoopSpec:
    """Parameter loop A-B dalam milidetik."""

    a_ms: int | None = None
    b_ms: int | None = None
    count: int = 0  # 0 = tanpa batas


class PlayerEngineListener:
    """Callback interface untuk perubahan state engine.

    Subclass di lapisan UI yang akan meneruskan ke Qt Signal. Tidak ada
    ketergantungan Qt di sini supaya core tetap portabel.
    """

    def on_position_changed(self, position_ms: int) -> None: ...

    def on_state_changed(self, state: PlayerState) -> None: ...

    def on_loop_iteration(self, iteration: int) -> None: ...

    def on_finished(self) -> None: ...

    def on_error(self, message: str) -> None: ...


class PlayerEngine:
    """Antarmuka abstrak pemutar audio."""

    # --- Siklus hidup ---
    def load(self, path: str | Path) -> None:
        raise NotImplementedError

    def unload(self) -> None:
        raise NotImplementedError

    # --- Kontrol ---
    def play(self) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def seek(self, position_ms: int) -> None:
        raise NotImplementedError

    def set_speed(self, speed: float) -> None:
        raise NotImplementedError

    def set_volume(self, volume: float) -> None:
        raise NotImplementedError

    def set_loop(self, spec: LoopSpec) -> None:
        raise NotImplementedError

    def clear_loop(self) -> None:
        raise NotImplementedError

    # --- Kueri ---
    @property
    def state(self) -> PlayerState:
        raise NotImplementedError

    @property
    def position_ms(self) -> int:
        raise NotImplementedError

    @property
    def duration_ms(self) -> int:
        raise NotImplementedError

    @property
    def speed(self) -> float:
        raise NotImplementedError

    @property
    def volume(self) -> float:
        raise NotImplementedError

    @property
    def loaded_path(self) -> Path | None:
        raise NotImplementedError

    # --- Listener ---
    def add_listener(self, listener: PlayerEngineListener) -> None:
        raise NotImplementedError

    def remove_listener(self, listener: PlayerEngineListener) -> None:
        raise NotImplementedError

    def poll(self) -> None:
        """Dipanggil berkala dari UI thread (~30 Hz) untuk emit posisi dan event loop."""
        ...

    def shutdown(self) -> None:
        """Bebaskan resource (wajib dipanggil sebelum exit)."""
        ...


class MpvEngine(PlayerEngine):
    """Implementasi PlayerEngine berbasis python-mpv (libmpv)."""

    def __init__(self, *, initial_volume: float = 0.8) -> None:
        # Import di sini agar jika library tidak tersedia, caller tahu saat
        # instansiasi, bukan saat import module.
        import mpv  # noqa: F401  (import-untyped ditangani di pyproject.toml overrides)

        self._mpv = mpv.MPV(
            vo="null",
            video=False,
            audio_pitch_correction="yes",
            af="scaletempo2",
            volume=initial_volume * 100.0,
            speed=1.0,
            ab_loop_count=0,
            terminal=False,
            msg_level="all=warn",
            log_handler=None,
        )
        self._listeners: list[PlayerEngineListener] = []
        self._lock = threading.RLock()
        self._state: PlayerState = PlayerState.IDLE
        self._loaded_path: Path | None = None
        self._duration_ms: int = 0
        self._last_loop_count: int = 0

        # mpv event callback (dijalankan di thread internal mpv)
        self._mpv.register_event_callback(self._on_mpv_event)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _notify_state(self, new_state: PlayerState) -> None:
        with self._lock:
            if new_state == self._state and new_state not in (
                PlayerState.PLAYING,
                PlayerState.PAUSED,
            ):
                return
            self._state = new_state
            snap = list(self._listeners)
        for listener in snap:
            try:
                listener.on_state_changed(new_state)
            except Exception:  # pragma: no cover - defensive
                pass

    def _on_mpv_event(self, event: object) -> None:
        # mpv Event memiliki atribut 'event_id' (int/enum). Kita gunakan
        # nama string yang tersedia via `event.name`.
        try:
            name = getattr(event, "name", None) or str(getattr(event, "event_id", "?"))
        except Exception:
            name = str(event)

        if name == "end-file":
            # Pastikan ini benar-benar selesai, bukan ganti file
            try:
                reason = getattr(event, "reason", None)
                if reason == "eof" or (isinstance(reason, int) and reason == 0):
                    self._notify_state(PlayerState.IDLE)
                    snap = list(self._listeners)
                    for listener in snap:
                        try:
                            listener.on_finished()
                        except Exception:
                            pass
            except Exception:
                pass
        elif name in ("file-loaded",):
            try:
                dur = self._mpv.duration
                self._duration_ms = int(round(float(dur) * 1000)) if dur is not None else 0
            except Exception:
                self._duration_ms = 0
            self._notify_state(PlayerState.LOADED)
        elif name in ("playback-restart",):
            self._notify_state(PlayerState.PLAYING)

    def _read_position_ms(self) -> int:
        try:
            val = self._mpv.time_pos
            if val is None:
                return 0
            return int(round(float(val) * 1000))
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Siklus hidup
    # ------------------------------------------------------------------
    def load(self, path: str | Path) -> None:
        p = Path(path).resolve()
        if not p.is_file():
            for listener in list(self._listeners):
                try:
                    listener.on_error(f"File tidak ada: {p}")
                except Exception:
                    pass
            self._notify_state(PlayerState.ERROR)
            return
        with self._lock:
            self._loaded_path = p
            self._last_loop_count = 0
            self._mpv.ab_loop_a = "no"
            self._mpv.ab_loop_b = "no"
            self._mpv.ab_loop_count = 0
            try:
                self._mpv.loadfile(str(p), "replace")
            except Exception as exc:
                for listener in list(self._listeners):
                    try:
                        listener.on_error(f"Gagal load: {exc}")
                    except Exception:
                        pass
                self._notify_state(PlayerState.ERROR)

    def unload(self) -> None:
        with self._lock:
            try:
                self._mpv.stop()
            except Exception:
                pass
            self._loaded_path = None
            self._duration_ms = 0
            self._notify_state(PlayerState.IDLE)

    # ------------------------------------------------------------------
    # Kontrol
    # ------------------------------------------------------------------
    def play(self) -> None:
        with self._lock:
            if self._loaded_path is None:
                return
            try:
                self._mpv.pause = False
            except Exception:
                return
            self._notify_state(PlayerState.PLAYING)

    def pause(self) -> None:
        with self._lock:
            try:
                self._mpv.pause = True
            except Exception:
                return
            self._notify_state(PlayerState.PAUSED)

    def stop(self) -> None:
        with self._lock:
            try:
                self._mpv.stop()
                # Re-load file agar posisi kembali ke 0 (mpv default stop
                # kadang tidak mengosongkan playhead)
                if self._loaded_path is not None and self._loaded_path.is_file():
                    self._mpv.loadfile(str(self._loaded_path), "replace")
                    self._mpv.pause = True
            except Exception:
                pass
            self._notify_state(PlayerState.LOADED)

    def seek(self, position_ms: int) -> None:
        pos = max(0, int(position_ms))
        with self._lock:
            try:
                seconds = pos / 1000.0
                self._mpv.seek(seconds, reference="absolute", precision="exact")
            except Exception:
                pass

    def set_speed(self, speed: float) -> None:
        clamped = max(0.25, min(2.0, float(speed)))
        with self._lock:
            try:
                self._mpv.speed = clamped
            except Exception:
                pass

    def set_volume(self, volume: float) -> None:
        clamped = max(0.0, min(1.0, float(volume)))
        with self._lock:
            try:
                self._mpv.volume = clamped * 100.0
            except Exception:
                pass

    def set_loop(self, spec: LoopSpec) -> None:
        with self._lock:
            try:
                if spec.a_ms is not None and spec.b_ms is not None and spec.b_ms > spec.a_ms:
                    self._mpv.ab_loop_a = spec.a_ms / 1000.0
                    self._mpv.ab_loop_b = spec.b_ms / 1000.0
                    self._mpv.ab_loop_count = max(0, int(spec.count))
                else:
                    self.clear_loop()
            except Exception:
                self.clear_loop()

    def clear_loop(self) -> None:
        with self._lock:
            try:
                self._mpv.ab_loop_a = "no"
                self._mpv.ab_loop_b = "no"
                self._mpv.ab_loop_count = 0
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Kueri
    # ------------------------------------------------------------------
    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def position_ms(self) -> int:
        return self._read_position_ms()

    @property
    def duration_ms(self) -> int:
        if self._duration_ms > 0:
            return self._duration_ms
        try:
            dur = self._mpv.duration
            self._duration_ms = int(round(float(dur) * 1000)) if dur is not None else 0
        except Exception:
            pass
        return self._duration_ms

    @property
    def speed(self) -> float:
        try:
            return float(self._mpv.speed)
        except Exception:
            return 1.0

    @property
    def volume(self) -> float:
        try:
            return float(self._mpv.volume) / 100.0
        except Exception:
            return 0.8

    @property
    def loaded_path(self) -> Path | None:
        return self._loaded_path

    # ------------------------------------------------------------------
    # Listener
    # ------------------------------------------------------------------
    def add_listener(self, listener: PlayerEngineListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: PlayerEngineListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    # Polling hook: dipanggil dari UI thread ~30 Hz. Karena python-mpv
    # observer terkadang telat/berjalan di thread lain, polling lebih aman
    # untuk position update UI.
    def poll(self) -> None:
        """Panggil secara berkala dari thread UI untuk emit position & loop iteration."""
        if self._loaded_path is None:
            return
        pos = self._read_position_ms()
        snap_pos = list(self._listeners)
        for listener in snap_pos:
            try:
                listener.on_position_changed(pos)
            except Exception:
                pass

        # Cek loop iteration via ab-loop-count property (berkurang setiap loop)
        try:
            remaining = int(self._mpv.ab_loop_count)
            if remaining >= 0:
                current = remaining
                if current != self._last_loop_count and self._last_loop_count != 0:
                    iteration = max(0, self._last_loop_count - current)
                    if iteration > 0:
                        for listener in list(self._listeners):
                            try:
                                listener.on_loop_iteration(iteration)
                            except Exception:
                                pass
                self._last_loop_count = current
        except Exception:
            pass

    def shutdown(self) -> None:
        with self._lock:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._loaded_path = None
            self._state = PlayerState.IDLE
            self._listeners.clear()
