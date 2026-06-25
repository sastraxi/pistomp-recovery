# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy

from pistomp_recovery.constants import INIT_STAMP, LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.spi_timing import transfer_ms as spi_transfer_ms
from pistomp_recovery.ui.widgets.misc import Box, union_rects

if TYPE_CHECKING:
    import pygame

logger = logging.getLogger(__name__)


def _read_spidev_bufsiz() -> int:
    try:
        with open("/sys/module/spidev/parameters/bufsiz", "r") as f:
            return int(f.read().strip())
    except Exception:
        return 4096


SPIDEV_BUFSIZ: int = _read_spidev_bufsiz()


class LcdSpi:
    """ILI9341 SPI LCD driver, ported from ``../pi-stomp/uilib/lcd_ili9341.py``.

    The panel is driven landscape-native: ``__init__`` rewrites MADCTL to
    ``0xE8`` (flip) or ``0x28`` (non-flip) so a 320x240 pygame surface maps
    straight onto the panel address window with no per-push rotation or
    coordinate swap. Full and partial pushes share one code path — subsurface
    -> RGB565 pack via numpy -> ``_block_fast`` (single SPI lock/CS, ``os.write``
    chunked by ``SPIDEV_BUFSIZ``). This is the proven pi-stomp implementation;
    do not reinvent a blit path here.
    """

    def __init__(self, baudrate: int = 80_000_000, flip: bool = True) -> None:
        self._baudrate: int = baudrate
        self._flip: bool = flip
        self._disp: object | None = None
        self._lock: threading.Lock = threading.Lock()
        self._pixels: "object | None" = None  # numpy.ndarray, allocated in init()

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

        # Bypass Adafruit's six-lock-per-block write with a single-lock/CS path.
        self._disp._block = self._block_fast  # type: ignore[union-attr]

        if not self.has_system_splash:
            self.clear()  # full-panel black while still in Adafruit's portrait MADCTL
            self._create_stamp()

        # Drive the panel landscape-native so 320x240 surfaces push row-major
        # with no rotation. Adafruit's init leaves MADCTL=0x48 (portrait);
        # re-assert the lcd-splash landscape mode. ``flip`` here follows
        # recovery's historical convention (True = mirror both axes, matching
        # the old 180° pygame rotation), which is the inverse of pi-stomp's
        # ``LcdIli9341.flip`` flag.
        madctl: int = self._madctl_for(self._flip)
        self._disp.write(0x36, bytes([madctl]))  # type: ignore[union-attr]

        self._pixels = numpy.empty((LCD_HEIGHT, LCD_WIDTH, 2), dtype=numpy.uint8)
        logger.info("LCD initialized: %dx%d (flip=%s)", LCD_WIDTH, LCD_HEIGHT, self._flip)

    def _create_stamp(self) -> None:
        try:
            Path(INIT_STAMP).touch()
        except OSError:
            pass

    @staticmethod
    def _madctl_for(flip: bool) -> int:
        """MADCTL byte for landscape-native orientation.

        ILI9341 MADCTL bits: MY (row order), MX (column order), MV (row/col
        swap = landscape), BGR. ``0xE8`` (MY|MX|MV|BGR) mirrors both axes;
        ``0x28`` (MV|BGR) does not. ``flip`` follows recovery's historical
        convention (True = mirror both axes, the old 180° pygame rotation),
        which is the inverse of pi-stomp's ``LcdIli9341.flip`` flag.
        """
        return 0xE8 if flip else 0x28

    def _block_fast(self, x0: int, y0: int, x1: int, y1: int, data: bytes | None = None) -> None:
        """Single-lock/CS block write, ported verbatim from pi-stomp.

        Bypasses ``adafruit_rgb_display``'s per-step lock/CS dance and writes
        column-set / page-set / RAM-write commands directly over ``os.write``,
        chunked to the spidev buffer size. ``data=None`` falls back to the
        upstream ``DisplaySPI._block`` (used only by ``clear``/``fill``).
        """
        if data is None:
            import adafruit_rgb_display.rgb as rgb  # type: ignore[import-untyped]

            return rgb.DisplaySPI._block(self._disp, x0, y0, x1, y1, data)  # type: ignore[union-attr]

        disp = self._disp
        assert disp is not None
        spi_dev = disp.spi_device  # type: ignore[union-attr]
        spi = spi_dev.spi  # type: ignore[union-attr]
        cs = spi_dev.chip_select  # type: ignore[union-attr]
        dc = disp.dc_pin  # type: ignore[union-attr]
        pure_spi = spi._spi._spi  # type: ignore[union-attr]
        fd = pure_spi.handle  # type: ignore[union-attr]

        while not spi.try_lock():  # type: ignore[union-attr]
            import time

            time.sleep(0)

        try:
            spi.configure(  # type: ignore[union-attr]
                baudrate=spi_dev.baudrate,  # type: ignore[union-attr]
                polarity=spi_dev.polarity,  # type: ignore[union-attr]
                phase=spi_dev.phase,  # type: ignore[union-attr]
            )

            if cs:
                cs.value = spi_dev.cs_active_value  # type: ignore[union-attr]

            dc.value = 0
            os.write(fd, bytes([disp._COLUMN_SET]))  # type: ignore[union-attr]
            dc.value = 1
            os.write(fd, disp._encode_pos(x0 + disp._X_START, x1 + disp._X_START))  # type: ignore[union-attr]

            dc.value = 0
            os.write(fd, bytes([disp._PAGE_SET]))  # type: ignore[union-attr]
            dc.value = 1
            os.write(fd, disp._encode_pos(y0 + disp._Y_START, y1 + disp._Y_START))  # type: ignore[union-attr]

            dc.value = 0
            os.write(fd, bytes([disp._RAM_WRITE]))  # type: ignore[union-attr]
            dc.value = 1

            mv = memoryview(data)
            for i in range(0, len(data), SPIDEV_BUFSIZ):
                os.write(fd, mv[i : i + SPIDEV_BUFSIZ])
        finally:
            if cs:
                cs.value = not spi_dev.cs_active_value  # type: ignore[union-attr]
            spi.unlock()  # type: ignore[union-attr]

    def update(self, surface: pygame.Surface, rects: list[Box] | None = None) -> None:
        """Push (a sub-rect of) the composed pygame surface to the LCD.

        Converts surface -> RGB565 via numpy and writes via ``_block_fast``.
        The panel runs landscape-native (MADCTL set in ``init``) so surface
        coords map straight to the panel address window — no rotation, no
        coordinate swap, one path for full and partial pushes.
        """
        with self._lock:
            if self._disp is None:
                return

            import pygame

            dirty: Box | None = union_rects(rects) if rects else None
            if dirty is not None and dirty.is_empty():
                return
            if dirty is None:
                dirty = Box(0, 0, LCD_WIDTH, LCD_HEIGHT)

            img_width, img_height = surface.get_size()
            x1, y1 = dirty.x, dirty.y
            x1 = max(0, min(x1, img_width))
            y1 = max(0, min(y1, img_height))
            x2 = max(x1, min(dirty.right, img_width))
            y2 = max(y1, min(dirty.bottom, img_height))
            if x2 <= x1 or y2 <= y1:
                return

            cropped = x1 != 0 or y1 != 0 or x2 != img_width or y2 != img_height
            sub = surface.subsurface(pygame.Rect(x1, y1, x2 - x1, y2 - y1)) if cropped else surface

            sw, sh = sub.get_size()

            arr = pygame.surfarray.pixels3d(sub).transpose(1, 0, 2)
            pix = self._pixels[:sh, :sw]  # type: ignore[index]
            g = arr[:, :, 1]
            pix[:, :, 0] = (arr[:, :, 0] & 0xF8) | (g >> 5)
            pix[:, :, 1] = ((g & 0x1C) << 3) | (arr[:, :, 2] >> 3)
            pixels_bytes: bytes = pix.tobytes()

            self._disp._block(x1, y1, x1 + sw - 1, y1 + sh - 1, pixels_bytes)  # type: ignore[union-attr]

    def clear(self) -> None:
        if self._disp is not None:
            self._disp.fill(0)  # type: ignore[union-attr]

    def transfer_ms(self, rect: Box | None = None) -> float:
        """Estimated milliseconds to push ``rect`` (or the whole panel) over SPI."""
        if rect is None:
            pixels: int = LCD_WIDTH * LCD_HEIGHT
        else:
            pixels = max(0, rect.w) * max(0, rect.h)
        return spi_transfer_ms(pixels, float(self._baudrate))
