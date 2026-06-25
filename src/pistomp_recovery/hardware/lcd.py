# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from pistomp_recovery.constants import INIT_STAMP, LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.spi_timing import transfer_ms as spi_transfer_ms
from pistomp_recovery.ui.widgets.misc import Box, union_rects

if TYPE_CHECKING:
    import pygame

logger = logging.getLogger(__name__)


class LcdSpi:
    def __init__(self, baudrate: int = 80_000_000, flip: bool = True) -> None:
        self._baudrate: int = baudrate
        self._flip: bool = flip
        self._disp: object | None = None
        self._lock: threading.Lock = threading.Lock()

    @property
    def width(self) -> int:
        return LCD_WIDTH

    @property
    def height(self) -> int:
        return LCD_HEIGHT

    @property
    def has_system_splash(self) -> bool:
        return Path(INIT_STAMP).exists()

    def init(self) -> None:
        try:
            import board  # type: ignore[import-untyped]
            import digitalio  # type: ignore[import-untyped]
            from adafruit_rgb_display import ili9341  # type: ignore[import-untyped]
        except ImportError:
            logger.error("LCD dependencies not available (board, adafruit_rgb_display)")
            raise

        # Speed up per-frame transfers before the first blit (see driver_patch).
        from pistomp_recovery.hardware import driver_patch

        driver_patch.apply()

        spi = board.SPI()  # type: ignore[union-attr]
        cs_pin = digitalio.DigitalInOut(board.CE0)  # type: ignore[union-attr]
        dc_pin = digitalio.DigitalInOut(board.D6)  # type: ignore[union-attr]
        rst_pin = digitalio.DigitalInOut(board.D5)  # type: ignore[union-attr]

        rst = None if self.has_system_splash else rst_pin  # type: ignore[assignment]

        self._disp = ili9341.ILI9341(  # type: ignore[union-attr]
            spi,
            cs=cs_pin,
            dc=dc_pin,
            rst=rst,
            baudrate=self._baudrate,
        )

        if not self.has_system_splash:
            self._create_stamp()

        logger.info("LCD initialized: %dx%d", LCD_WIDTH, LCD_HEIGHT)

    def _create_stamp(self) -> None:
        try:
            Path(INIT_STAMP).touch()
        except OSError:
            pass

    def update(self, surface: pygame.Surface, rects: list[Box] | None = None) -> None:
        with self._lock:
            if self._disp is None:
                return

            dirty: Box | None = union_rects(rects) if rects else None
            if dirty is not None and dirty.is_empty():
                return

            if dirty is None:
                self._push_full(surface)
            else:
                self._push_rect(surface, dirty)

    def _push_full(self, surface: pygame.Surface) -> None:
        """Whole-frame push (legacy path)."""
        import pygame
        from PIL import Image  # type: ignore[import-untyped]

        img: pygame.Surface = pygame.transform.rotate(
            surface, 180 if self._flip else 0
        )
        rgb: bytes = pygame.image.tostring(img, "RGB")
        pil_img: Image.Image = Image.frombytes("RGB", (LCD_WIDTH, LCD_HEIGHT), rgb)
        self._disp.image(pil_img, 270 if self._flip else 90)  # type: ignore[union-attr]

    def _push_rect(self, surface: pygame.Surface, rect: Box) -> None:
        """Partial push: ship only the dirty sub-rect over SPI.

        Coordinate transform (same formula for flip and non-flip): a surface
        rect ``(sx, sy, sw, sh)`` maps to panel address window
        ``(LCD_HEIGHT - sy - sh, sx, sh, sw)`` because the rotation chain
        (pygame 180° + PIL 270° CCW, or PIL 90° CCW alone) swaps the axes.
        The panel is driven in its native portrait orientation (240×320);
        ``disp.image(sub, rotation, x, y)`` handles the per-rect rotation and
        calls ``_block`` with the windowed coordinates.
        """
        import pygame
        from PIL import Image  # type: ignore[import-untyped]

        sx, sy, sw, sh = rect.x, rect.y, rect.w, rect.h
        # Clamp to surface bounds.
        sx = max(0, min(sx, LCD_WIDTH))
        sy = max(0, min(sy, LCD_HEIGHT))
        sw = max(0, min(sw, LCD_WIDTH - sx))
        sh = max(0, min(sh, LCD_HEIGHT - sy))
        if sw == 0 or sh == 0:
            return

        sub: pygame.Surface = surface.subsurface(pygame.Rect(sx, sy, sw, sh))
        if self._flip:
            sub = pygame.transform.rotate(sub, 180)
        rgb: bytes = pygame.image.tostring(sub, "RGB")
        pil_sub: Image.Image = Image.frombytes("RGB", (sw, sh), rgb)

        panel_x: int = LCD_HEIGHT - sy - sh
        panel_y: int = sx
        self._disp.image(  # type: ignore[union-attr]
            pil_sub, 270 if self._flip else 90, x=panel_x, y=panel_y
        )

    def clear(self) -> None:
        if self._disp is not None:
            from PIL import Image  # type: ignore[import-untyped]

            black: Image.Image = Image.new("RGB", (LCD_WIDTH, LCD_HEIGHT), (0, 0, 0))
            self._disp.image(black, 270 if self._flip else 90)  # type: ignore[union-attr]

    def transfer_ms(self, rect: Box | None = None) -> float:
        """Estimated milliseconds to push ``rect`` (or the whole panel) over SPI."""
        if rect is None:
            pixels: int = LCD_WIDTH * LCD_HEIGHT
        else:
            pixels = max(0, rect.w) * max(0, rect.h)
        return spi_transfer_ms(pixels, float(self._baudrate))
