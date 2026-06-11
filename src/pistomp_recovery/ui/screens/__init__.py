from __future__ import annotations

from typing import Callable

import pygame

from pistomp_recovery.ui.widgets.misc import InputEvent


class Screen:
    def __init__(self, surface: pygame.Surface) -> None:
        self._surface: pygame.Surface = surface
        self._on_back: Callable[[], None] | None = None

    def draw(self) -> None:
        raise NotImplementedError

    def handle_event(self, event: InputEvent) -> bool:
        return False

    def set_back_callback(self, callback: Callable[[], None] | None) -> None:
        self._on_back = callback

    def _go_back(self) -> None:
        if self._on_back is not None:
            self._on_back()
