"""State machine mode loop GuitarLoop sesuai PRD §6.2 dan §6.3.

- Mode A_B       : pengguna pilih A dan B (ms atau marker ID)

- Mode BAGIAN    : marker ke-N → marker ke-(N+1) (berurutan waktu)

- Mode AWAL_MARKER : 0 → marker terpilih

- Mode MARKER_AKHIR : marker terpilih → durasi

- Jumlah ulangan (repeat_count): 1..99, atau 0 = tanpa batas (∞)

- Action setelah selesai: 'stop' (default) atau 'continue'

- Terhubung ke PlayerEngine via set_loop(LoopSpec) / clear_loop()

- Emit event via listener (sama interface engine listener):
    • on_loop_iteration(delta_count)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from guitarloop.core.engine import LoopSpec, PlayerEngine, PlayerEngineListener
from guitarloop.core.markers import MarkerCollection


class LoopMode(enum.StrEnum):
    OFF = "off"
    A_B = "a_b"
    BAGIAN = "bagian"
    AWAL_MARKER = "awal_marker"
    MARKER_AKHIR = "marker_akhir"


class LoopAfterAction(enum.StrEnum):
    STOP = "stop"
    CONTINUE = "continue"


@dataclass
class LoopConfig:
    mode: LoopMode = LoopMode.OFF
    # A_B mode: A & B bisa berupa ms murni atau marker_id (nanti resolve ke ms)
    loop_a_ms: int | None = None
    loop_b_ms: int | None = None
    marker_a_id: str | None = None
    marker_b_id: str | None = None
    # BAGIAN / AWAL_MARKER / MARKER_AKHIR mode:
    marker_index: int = 0
    # Repeat
    repeat_count: int = 5  # 0 = ∞
    after: LoopAfterAction = LoopAfterAction.STOP
    # Akurasi: jarak ambang dianggap "melewati B" (ms)
    loop_done_threshold_ms: int = 8

    def is_infinite(self) -> bool:
        return self.repeat_count <= 0


class LoopController(PlayerEngineListener):
    """Mengatur mode loop & iterasi. Terhubung ke engine."""

    def __init__(
        self,
        engine: PlayerEngine,
        markers: MarkerCollection,
        *,
        listener: PlayerEngineListener | None = None,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._markers = markers
        self._listener = listener
        self._config = LoopConfig()
        self._duration_ms: int = 0
        # Internal state loop
        self._iteration_done: int = 0  # berapa kali sudah terjadi loop (selesai 1 siklus)
        self._active: bool = False  # loop aktif di engine
        self._last_position: int = -1  # posisi terakhir untuk deteksi wrap-around

    # ------------------------------------------------------------------
    # Attachment
    # ------------------------------------------------------------------
    def set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self._reapply()

    def set_markers_ref(self, markers: MarkerCollection) -> None:
        self._markers = markers

    def set_listener(self, listener: PlayerEngineListener | None) -> None:
        self._listener = listener

    # ------------------------------------------------------------------
    # Query current state
    # ------------------------------------------------------------------
    @property
    def config(self) -> LoopConfig:
        return self._config

    @property
    def active(self) -> bool:
        return self._active

    @property
    def iteration_done(self) -> int:
        return self._iteration_done

    def total_expected(self) -> int | None:
        """Return total loop yang diharapkan, None = ∞."""
        return None if self._config.is_infinite() else self._config.repeat_count

    def resolve_bounds_ms(self) -> tuple[int, int] | None:
        """Return (start_ms, end_ms) jika mode aktif punya batas valid.

        Return None jika mode OFF atau batas invalid.
        """
        if self._config.mode == LoopMode.OFF:
            return None
        markers = list(self._markers)
        dur = max(self._duration_ms, 1)
        if self._config.mode == LoopMode.A_B:
            a, b = self._config.loop_a_ms, self._config.loop_b_ms
            if a is not None and b is not None and b > a + LoopConfig.loop_done_threshold_ms:
                return (a, b)
            return None
        if self._config.mode == LoopMode.AWAL_MARKER:
            if 0 <= self._config.marker_index < len(markers):
                end = markers[self._config.marker_index].time_ms
                if end > LoopConfig.loop_done_threshold_ms:
                    return (0, end)
            return None
        if self._config.mode == LoopMode.MARKER_AKHIR:
            if 0 <= self._config.marker_index < len(markers):
                start = markers[self._config.marker_index].time_ms
                if dur > start + LoopConfig.loop_done_threshold_ms:
                    return (start, dur)
            return None
        if self._config.mode == LoopMode.BAGIAN:
            idx = self._config.marker_index
            if 0 <= idx < max(0, len(markers) - 1):
                start = markers[idx].time_ms
                end = markers[idx + 1].time_ms
                if end > start + LoopConfig.loop_done_threshold_ms:
                    return (start, end)
            return None
        return None

    # ------------------------------------------------------------------
    # Konfigurasi (dipanggil oleh UI)
    # ------------------------------------------------------------------
    def set_mode(self, mode: LoopMode) -> None:
        self._config.mode = mode
        self._reapply()

    def set_repeat_count(self, count: int) -> None:
        self._config.repeat_count = max(0, int(count))
        self._reapply()

    def set_after_action(self, action: LoopAfterAction) -> None:
        self._config.after = action

    def set_ab_ms(self, a_ms: int, b_ms: int) -> None:
        self._config.mode = LoopMode.A_B
        self._config.marker_a_id = None
        self._config.marker_b_id = None
        self._config.loop_a_ms = max(0, int(a_ms))
        self._config.loop_b_ms = max(0, int(b_ms))
        self._reapply()

    def set_ab_markers(self, marker_a_id: str, marker_b_id: str) -> bool:
        idx_a = self._markers.index_of(marker_a_id)
        idx_b = self._markers.index_of(marker_b_id)
        if idx_a < 0 or idx_b < 0 or idx_a == idx_b:
            return False
        list_m = list(self._markers)
        t_a = list_m[idx_a].time_ms
        t_b = list_m[idx_b].time_ms
        if abs(t_b - t_a) < LoopConfig.loop_done_threshold_ms:
            return False
        self._config.mode = LoopMode.A_B
        self._config.marker_a_id = marker_a_id
        self._config.marker_b_id = marker_b_id
        if t_a <= t_b:
            self._config.loop_a_ms, self._config.loop_b_ms = t_a, t_b
        else:
            self._config.loop_a_ms, self._config.loop_b_ms = t_b, t_a
        self._reapply()
        return True

    def set_bagian(self, marker_index: int) -> None:
        self._config.mode = LoopMode.BAGIAN
        self._config.marker_index = int(marker_index)
        self._reapply()

    def set_awal_ke_marker(self, marker_index: int) -> None:
        self._config.mode = LoopMode.AWAL_MARKER
        self._config.marker_index = int(marker_index)
        self._reapply()

    def set_marker_ke_akhir(self, marker_index: int) -> None:
        self._config.mode = LoopMode.MARKER_AKHIR
        self._config.marker_index = int(marker_index)
        self._reapply()

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable loop tanpa ubah mode (shortcut L)."""
        if not enabled:
            self.deactivate()
            self._config.mode = LoopMode.OFF
        else:
            if self._config.mode == LoopMode.OFF:
                self._config.mode = LoopMode.BAGIAN
            self._reapply()

    def toggle(self) -> None:
        self.set_enabled(self._config.mode == LoopMode.OFF)

    # ------------------------------------------------------------------
    # Engine apply
    # ------------------------------------------------------------------
    def deactivate(self) -> None:
        if self._active:
            self._engine.clear_loop()
        self._active = False
        self._iteration_done = 0
        self._last_position = -1

    def reset_iteration_counter(self) -> None:
        self._iteration_done = 0

    def _reapply(self) -> None:
        bounds = self.resolve_bounds_ms()
        if bounds is None or self._config.mode == LoopMode.OFF:
            self.deactivate()
            return
        start_ms, end_ms = bounds
        # Kita biarkan engine loop tanpa batas count native.
        # Counter iterasi finite di-manage sendiri di tick() agar akurat
        # (mpv ab-loop-count kadang telat update dari python observer).
        self._engine.set_loop(LoopSpec(a_ms=start_ms, b_ms=end_ms, count=0))
        self._active = True

    # ------------------------------------------------------------------
    # Dipanggil ~30 Hz dari polling UI thread (sama seperti engine.poll())
    #
    # CATATAN V0.5: Deteksi wrap-around TIDAK LAGI di sini.
    # Karena kita memakai SOFTWARE LOOP FALLBACK 100% (manual seek ke A
    # via MainWindow._on_poll), kita TAHU PERSIS kapan wrap terjadi.
    # MainWindow akan MEMANGGIL method public force_wrap_occurred()
    # SEGERA SETELAH seek ke titik A. Ini 100% akurat & menghindari
    # double counting akibat prev_position lag.
    # ------------------------------------------------------------------
    def tick(self, position_ms: int) -> None:
        if position_ms < 0:
            self._last_position = position_ms
            return
        # Update jejak posisi terakhir (untuk debugging / future use).
        self._last_position = position_ms

    def force_wrap_occurred(self) -> None:
        """Public method: INFORMASIKAN bahwa WRAP BARU TERJADI.

        Dipanggil oleh MainWindow._on_poll SEGERA SETELAH software loop manual
        seek posisi dari (>= B) kembali ke (A). Ini lebih akurat daripada
        hanya mengandalkan perbandingan prev_position vs position_ms karena
        engine.seek() update posisi ke A SEBELUM tick() dipanggil lagi
        (jadi prev_position sudah = A pada detik pertama setelah wrap).
        """
        self._on_loop_iteration_completed()

    def _on_loop_iteration_completed(self) -> None:
        self._iteration_done += 1
        delta = 1
        if self._listener is not None:
            try:
                self._listener.on_loop_iteration(delta)
            except Exception:
                pass
        expected = self.total_expected()
        if expected is None:
            return
        if self._iteration_done >= expected:
            bounds = self.resolve_bounds_ms()
            start_ms = 0
            if bounds is not None:
                start_ms = bounds[0]
            # Selesai N iterasi: hapus loop dari engine (supaya tidak balik lagi)
            self._engine.clear_loop()
            self._active = False
            if self._config.after == LoopAfterAction.STOP:
                self._engine.pause()
                self._engine.seek(start_ms)
            # Jika after=continue: biarkan play, loop sudah dilepas.
