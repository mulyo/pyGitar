"""Adapter yang meneruskan callback PlayerEngineListener ke Qt Signal.

Ini satu-satunya tempat di mana 'interface listener core' dihubungkan ke
mekanisme sinyal Qt. Core tetap bersih dari PySide6.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from guitarloop.core.engine import PlayerEngineListener, PlayerState


class QtEngineBridge(QObject, PlayerEngineListener):
    """Meneruskan event engine menjadi Qt Signal (thread-safe via Qt queued)."""

    position_changed = Signal(int)  # position_ms
    state_changed = Signal(object)  # PlayerState
    loop_iteration = Signal(int)  # iteration count delta
    finished = Signal()
    error = Signal(str)  # message

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        PlayerEngineListener.__init__(self)

    def on_position_changed(self, position_ms: int) -> None:
        self.position_changed.emit(int(position_ms))

    def on_state_changed(self, state: PlayerState) -> None:
        self.state_changed.emit(state)

    def on_loop_iteration(self, iteration: int) -> None:
        self.loop_iteration.emit(int(iteration))

    def on_finished(self) -> None:
        self.finished.emit()

    def on_error(self, message: str) -> None:
        self.error.emit(str(message))
