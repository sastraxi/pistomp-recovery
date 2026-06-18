"""Emulator controls — software stubs for encoder and button input.

Each mock control provides injectable step()/press() methods so the
emulator window (or tests) can simulate hardware events.
"""

from __future__ import annotations

from pistomp_recovery.ui.widgets.misc import InputEvent


class FakeEncoderInput:
    """Encoder stub driven by inject() for step and press events."""

    def __init__(self) -> None:
        self._direction_queue: list[int] = []
        self._running: bool = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def poll(self) -> int:
        if self._direction_queue:
            return self._direction_queue.pop(0)
        return 0


class FakeInputManager:
    """InputManager backed by FakeEncoderInput, with click injection."""

    def __init__(self, encoder: FakeEncoderInput) -> None:
        self._encoder: FakeEncoderInput = encoder
        self._event_queue: list[InputEvent] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def inject_event(self, event: InputEvent) -> None:
        self._event_queue.append(event)

    def poll(self) -> list[InputEvent]:
        events: list[InputEvent] = []

        direction: int = self._encoder.poll()
        if direction > 0:
            events.append(InputEvent.RIGHT)
        elif direction < 0:
            events.append(InputEvent.LEFT)

        events.extend(self._event_queue)
        self._event_queue.clear()
        return events
