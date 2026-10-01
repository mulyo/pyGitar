"""Uji unit state machine LoopController (tanpa player riil).

Menggunakan FakeEngine untuk merekam pemanggilan set_loop / clear_loop / seek / pause.
"""

from __future__ import annotations

from typing import Any

import pytest

from guitarloop.core.engine import (
    LoopSpec,
    PlayerEngine,
    PlayerEngineListener,
    PlayerState,
)
from guitarloop.core.loop_controller import (
    LoopAfterAction,
    LoopController,
    LoopMode,
)
from guitarloop.core.markers import MarkerCollection


class FakePlayerEngine(PlayerEngine):
    """Palsu PlayerEngine (turunan abstrak base), cukup untuk test loop controller."""

    def __init__(self, duration_ms: int = 60_000, position_ms: int = 0) -> None:
        super().__init__()
        self.duration = duration_ms
        self.pos = position_ms
        self.calls_set_loop: list[LoopSpec] = []
        self.calls_clear_loop = 0
        self.calls_seek: list[int] = []
        self.calls_pause = 0
        self.speed_val = 1.0
        self.volume_val = 0.8
        self.state_val = PlayerState.LOADED
        self.listeners: list[Any] = []

    # ---- Antarmuka minimal digunakan oleh LoopController ----
    def set_loop(self, spec: LoopSpec) -> None:
        self.calls_set_loop.append(spec)

    def clear_loop(self) -> None:
        self.calls_clear_loop += 1

    def seek(self, position_ms: int) -> None:
        self.calls_seek.append(int(position_ms))
        self.pos = int(position_ms)

    def pause(self) -> None:
        self.calls_pause += 1

    def set_speed(self, s: float) -> None:
        self.speed_val = s

    def set_volume(self, v: float) -> None:
        self.volume_val = v

    def add_listener(self, _listener: PlayerEngineListener) -> None:
        self.listeners.append(_listener)

    def remove_listener(self, _listener: PlayerEngineListener) -> None:
        if _listener in self.listeners:
            self.listeners.remove(_listener)

    @property
    def duration_ms(self) -> int:
        return self.duration

    @property
    def position_ms(self) -> int:
        return self.pos

    @property
    def speed(self) -> float:
        return self.speed_val

    @property
    def volume(self) -> float:
        return self.volume_val

    @property
    def state(self) -> PlayerState:
        return self.state_val


@pytest.fixture()
def engine_1min() -> FakePlayerEngine:
    return FakePlayerEngine(duration_ms=60_000)


@pytest.fixture()
def col4() -> MarkerCollection:
    """4 markers: M1=2s, M2=10s, M3=25s, M4=45s (sisa sampai 60s = akhir)."""
    c = MarkerCollection()
    c.add(2_000)
    c.add(10_000)
    c.add(25_000)
    c.add(45_000)
    return c


class TestModeAB:
    def test_set_ab_ms_valid_activate(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_ab_ms(5_000, 15_000)
        assert len(engine_1min.calls_set_loop) == 1
        spec = engine_1min.calls_set_loop[-1]
        assert spec.a_ms == 5_000 and spec.b_ms == 15_000
        assert lc.active is True

    def test_set_ab_invalid_b_kurang_a_off(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_ab_ms(20_000, 5_000)  # B < A → batas invalid
        assert lc.resolve_bounds_ms() is None
        assert lc.active is False


class TestModeBagian:
    def test_bagian_2_marker_berurutan(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_bagian(1)  # index 1 → M2(10s) s/d M3(25s)
        bounds = lc.resolve_bounds_ms()
        assert bounds == (10_000, 25_000)
        assert engine_1min.calls_set_loop[-1].a_ms == 10_000
        assert engine_1min.calls_set_loop[-1].b_ms == 25_000

    def test_bagian_index_terakhir_invalid(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        # 4 markers → index valid BAGIAN = 0,1,2 (butuh Mn & Mn+1). index 3 invalid.
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_bagian(3)
        assert lc.resolve_bounds_ms() is None
        assert lc.active is False


class TestModeAwalAkhir:
    def test_awal_ke_marker(self, engine_1min: FakePlayerEngine, col4: MarkerCollection) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_awal_ke_marker(2)  # awal → M3 (25s)
        assert lc.resolve_bounds_ms() == (0, 25_000)

    def test_marker_ke_akhir(self, engine_1min: FakePlayerEngine, col4: MarkerCollection) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_marker_ke_akhir(3)  # M4(45s) → end 60s
        assert lc.resolve_bounds_ms() == (45_000, 60_000)


class TestToggle:
    def test_toggle_off_to_bagian_default(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        # Awalnya OFF (cast ke str value agar mypy tidak anggap literal constant overlap
        assert str(lc.config.mode) == str(LoopMode.OFF)
        lc.toggle()
        assert str(lc.config.mode) == str(LoopMode.BAGIAN)
        lc.toggle()
        assert str(lc.config.mode) == str(LoopMode.OFF)
        assert lc.active is False


class TestIterasiDanFinite:
    def test_finite_5kali_lalu_stop(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_ab_ms(0, 10_000)
        lc.set_repeat_count(5)
        lc.set_after_action(LoopAfterAction.STOP)
        assert lc.total_expected() == 5

        # Simulasikan playback: maju posisi sampai wrap 5x
        for _i in range(5):
            # Pura-pura play mendekati akhir batas → tick dengan posisi > akhir
            lc.tick(9_990)
            lc.tick(9_995)
            # Kembali ke awal (wrap)
            lc.tick(0)
        # Iteration count harus 5
        assert lc.iteration_done == 5
        # Iterasi ke-5 selesai: engine pause dan seek ke titik A
        assert engine_1min.calls_pause >= 1
        assert engine_1min.calls_clear_loop >= 1
        assert engine_1min.calls_seek[-1] == 0  # kembali ke A (0ms)
        assert lc.active is False

    def test_infinite_tidak_berhenti(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_ab_ms(0, 5_000)
        lc.set_repeat_count(0)  # ∞
        assert lc.total_expected() is None
        # 1000x wrap: active tetap True, tidak pernah pause/clear
        for _ in range(1000):
            lc.tick(4_995)
            lc.tick(0)
        assert lc.iteration_done == 1000
        assert lc.active is True
        assert engine_1min.calls_clear_loop == 0
        assert engine_1min.calls_pause == 0

    def test_mode_after_continue(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_ab_ms(0, 5_000)
        lc.set_repeat_count(1)
        lc.set_after_action(LoopAfterAction.CONTINUE)
        lc.tick(4_998)
        lc.tick(0)  # iterasi 1 selesai
        assert lc.iteration_done == 1
        # Tidak dipause
        assert engine_1min.calls_pause == 0
        # Loop diclear supaya tidak wrap lagi
        assert engine_1min.calls_clear_loop >= 1


class TestPerubahanMarker:
    def test_hapus_marker_dipakai_loop_bagian_reapply(
        self, engine_1min: FakePlayerEngine, col4: MarkerCollection
    ) -> None:
        lc = LoopController(engine_1min, col4)
        lc.set_duration_ms(engine_1min.duration_ms)
        lc.set_bagian(1)  # index 1 (M2=10s) sampai M3=25s
        assert lc.resolve_bounds_ms() == (10_000, 25_000)
        # Hapus M2 (index 1 setelah sort) — marker id M2
        id_m2 = col4[1].id
        col4.remove(id_m2)
        # Re-apply bounds (seolah MainWindow memanggil _reapply_loop_controller_bounds)
        lc.set_bagian(min(1, max(0, len(col4) - 2)))
        # Setelah hapus M2: markers jadi [2s, 25s, 45s]. Bagian(1) → 25s sd 45s
        assert lc.resolve_bounds_ms() == (25_000, 45_000)
