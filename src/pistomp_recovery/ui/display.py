from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pygame

from pistomp_recovery.constants import LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.pygame_init import init as pg_init

if TYPE_CHECKING:
    from pistomp_recovery.hardware.lcd import LcdSpi

logger = logging.getLogger(__name__)


class Display:
    def __init__(self, lcd: "LcdSpi | None" = None) -> None:
        self._lcd: "LcdSpi | None" = lcd
        self.width: int = LCD_WIDTH
        self.height: int = LCD_HEIGHT
        self._surface: pygame.Surface | None = None

    def init(self) -> None:
        pg_init()
        self._surface = pygame.Surface((self.width, self.height))
        self._surface.fill((0, 0, 0))
        if self._lcd is not None:
            self._lcd.init()
            self.update(self._surface)

    def update(self, surface: pygame.Surface) -> None:
        if self._lcd is not None:
            self._lcd.update(surface)

    @property
    def surface(self) -> pygame.Surface:
        assert self._surface is not None, "Display not initialized"
        return self._surface
