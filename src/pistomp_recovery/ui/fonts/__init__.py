# pyright: reportUnknownVariableType=false
"""Font wrapper using pygame._freetype with bundled DejaVu Sans.

Matches the pi-stomp font family. Bundled TTF files ensure
deterministic pixel-identical rendering across all platforms.
"""

from __future__ import annotations

import os

import pygame
import pygame._freetype as _freetype  # type: ignore[attr-defined]

from pistomp_recovery.pygame_init import init as _pg_init

_FONT_DIR: str = os.path.dirname(__file__)

_REGULAR: str = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
_BOLD: str = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")

SIZES: dict[str, int] = {
    "title": 22,
    "heading": 20,
    "body": 18,
    "small": 16,
    "status": 14,
}

_BOLD_SIZES: frozenset[int] = frozenset({SIZES["title"], SIZES["heading"]})


class SafeFont:
    """Drop-in replacement for pygame.font.Font that uses pygame._freetype."""

    def __init__(self, path: str | None, size: int) -> None:
        _pg_init()
        self._ft: _freetype.Font = _freetype.Font(path, size)  # type: ignore[assignment]

    def render(
        self, text: str, antialias: bool, color: tuple[int, int, int] | tuple[int, int, int, int]
    ) -> pygame.Surface:
        result = self._ft.render(text, color)  # type: ignore[union-attr]
        return result[0]

    def get_rect(self, text: str) -> pygame.Rect:
        return self._ft.get_rect(text)  # type: ignore[union-attr]

    def size(self, text: str) -> tuple[int, int]:
        rect = self.get_rect(text)
        return (rect.width, rect.height)

    @property
    def height(self) -> int:
        return self._ft.get_rect("Ag").height  # type: ignore[union-attr]


FONT_CACHE: dict[tuple[str, int], SafeFont] = {}


def get_font(size: int = 18, bold: bool | None = None) -> SafeFont:
    if bold is None:
        bold = size in _BOLD_SIZES
    path: str = _BOLD if bold else _REGULAR
    key: tuple[str, int] = (path, size)
    if key not in FONT_CACHE:
        FONT_CACHE[key] = SafeFont(path, size)
    return FONT_CACHE[key]
