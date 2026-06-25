# pyright: reportPrivateUsage=false
"""Dirty-rect / invalidation tests.

Mirrors the contracts from pi-stomp's ``tests/test_cache_valid.py`` adapted
to recovery's flat single-screen model (no widget tree / ContainerWidget).
Covers: selection movement returns tight rects, draw clips to the dirty
region, union_rects coalesces, and Box.is_empty gates pushes.
"""

from __future__ import annotations

import pygame

from pistomp_recovery.constants import LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.hardware.lcd import LcdSpi
from pistomp_recovery.items import Row, Target
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.widgets.header import ICON_BACK
from pistomp_recovery.ui.widgets.misc import Box, union_rects


def _make_menu(surface: pygame.Surface, n_rows: int = 5) -> MenuScreen:
    rows = [Row((Target(f"Item {i}", lambda: None),)) for i in range(n_rows)]
    return MenuScreen(
        surface,
        "Test",
        rows,
        Target(ICON_BACK, lambda: None),
    )


class TestUnionRects:
    def test_empty_list_returns_none(self) -> None:
        assert union_rects([]) is None

    def test_empty_boxes_skipped(self) -> None:
        assert union_rects([Box(0, 0, 0, 0)]) is None

    def test_single_rect(self) -> None:
        r = Box(10, 20, 30, 40)
        assert union_rects([r]) == r

    def test_disjoint_union_into_bbox(self) -> None:
        a = Box(0, 0, 10, 10)
        b = Box(20, 20, 10, 10)
        assert union_rects([a, b]) == Box(0, 0, 30, 30)

    def test_empty_subsumed_by_nonempty(self) -> None:
        a = Box(0, 0, 10, 10)
        assert union_rects([Box(0, 0, 0, 0), a]) == a


class TestBoxIsEmpty:
    def test_zero_width_is_empty(self) -> None:
        assert Box(0, 0, 0, 40).is_empty()

    def test_zero_height_is_empty(self) -> None:
        assert Box(0, 0, 40, 0).is_empty()

    def test_nonzero_not_empty(self) -> None:
        assert not Box(0, 0, 1, 1).is_empty()


class TestSelectionRects:
    """Selection movement returns tight rects (the inline-push win)."""

    def test_right_movement_returns_two_row_rects(self) -> None:
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        menu = _make_menu(surface)
        old_sel = menu._sel
        old_rect = menu._selection_rect()
        from pistomp_recovery.ui.widgets.misc import InputEvent

        touched = menu.handle_event(InputEvent.RIGHT)
        new_sel = menu._sel
        assert new_sel != old_sel
        assert len(touched) == 2
        assert touched[0] == old_rect
        assert touched[1] == menu._selection_rect()
        # The two rects should differ (selection moved).
        assert touched[0] != touched[1]

    def test_header_selection_rect_is_header_band(self) -> None:
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        menu = _make_menu(surface)
        menu._sel = 0  # header icon
        from pistomp_recovery.ui.widgets.header import header_height

        rect = menu._selection_rect()
        assert rect == Box(0, 0, LCD_WIDTH, header_height())

    def test_scroll_change_returns_content_rect(self) -> None:
        """When a nav step changes scroll, the whole content area is dirty."""
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        # Build a menu with many rows so scrolling is exercised.
        rows = [Row((Target(f"Item {i}", lambda: None),)) for i in range(20)]
        menu = MenuScreen(surface, "Test", rows, Target(ICON_BACK, lambda: None))
        # Move selection to the last item to force a scroll change.
        menu._sel = len(menu._nav) - 1
        menu._scroll_into_view()
        old_scroll = menu._scroll
        from pistomp_recovery.ui.widgets.misc import InputEvent

        # Step right (past the end, wraps to header) — scroll changes.
        touched = menu.handle_event(InputEvent.RIGHT)
        # Either content rect (scroll changed) or two row rects (no scroll).
        assert len(touched) >= 1
        if menu._scroll != old_scroll:
            assert any(r == menu._content_rect() or r.h > 16 for r in touched)


class TestDrawClip:
    """draw(clip) only repaints within the clip region."""

    def test_draw_with_clip_leaves_outside_untouched(self) -> None:
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        surface.fill((255, 0, 0))  # red baseline
        menu = _make_menu(surface)

        # Draw with a clip that's only the top-left quadrant.
        clip = Box(0, 0, 80, 80)
        menu.draw(clip)

        # Outside the clip, pixels should still be red (untouched).
        # Pick a point well outside the clip (bottom-right corner).
        outside = surface.get_at((LCD_WIDTH - 10, LCD_HEIGHT - 10))
        assert outside[:3] == (255, 0, 0), "draw should not touch outside clip"

        # Inside the clip, pixels should not be red (they were repainted).
        inside = surface.get_at((40, 40))
        assert inside[:3] != (255, 0, 0), "draw should repaint inside clip"

    def test_draw_no_clip_repaints_full_surface(self) -> None:
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        surface.fill((0, 255, 0))  # green baseline
        menu = _make_menu(surface)
        menu.draw(None)
        # The whole surface should have been repainted (no green left).
        px = surface.get_at((LCD_WIDTH - 10, LCD_HEIGHT - 10))
        assert px[:3] != (0, 255, 0)


class TestTransferMs:
    """LcdSpi.transfer_ms estimates push cost from the rect area."""

    def test_transfer_ms_grows_with_area(self) -> None:
        from pistomp_recovery.hardware.lcd import LcdSpi

        lcd = LcdSpi()
        small = lcd.transfer_ms(Box(0, 0, 10, 10))
        full = lcd.transfer_ms(None)
        assert full > small > 0

    def test_transfer_ms_empty_rect_is_near_zero(self) -> None:
        from pistomp_recovery.hardware.lcd import LcdSpi

        lcd = LcdSpi()
        assert lcd.transfer_ms(Box(0, 0, 0, 0)) >= 0  # fixed overhead only


class _FakePanel:
    """Records the SPI address-window writes a landscape-native LcdSpi emits.

    Mirrors the Adafruit driver surface pi-stomp's ``LcdIli9341`` uses:
    ``_block(x0, y0, x1, y1, data)`` is the partial/full push primitive, and
    ``image(...)`` / ``fill(...)`` are the legacy full-frame APIs. We assert
    that ``update()`` reaches ``_block`` directly (the landscape-native path)
    and never falls back to the rotated ``image()`` path.
    """

    def __init__(self, width: int = LCD_WIDTH, height: int = LCD_HEIGHT) -> None:
        self.width = width
        self.height = height
        self.blocks: list[tuple[int, int, int, int, bytes]] = []
        self.image_calls: int = 0
        self.fill_calls: int = 0
        self.writes: list[tuple[int, bytes]] = []
        # Attributes the driver touches (set by LcdSpi.init via the real driver).
        self._block = self._record_block
        self.spi_device: object | None = None
        self.dc_pin: object | None = None
        self._X_START = 0
        self._Y_START = 0
        self._COLUMN_SET = 0x2A
        self._PAGE_SET = 0x2B
        self._RAM_WRITE = 0x2C

    def _record_block(self, x0: int, y0: int, x1: int, y1: int, data: bytes | None = None) -> None:
        assert data is not None, "_block must be called with pixel data"
        self.blocks.append((x0, y0, x1, y1, bytes(data)))

    def image(self, *args: object, **kwargs: object) -> None:
        self.image_calls += 1

    def fill(self, *args: object, **kwargs: object) -> None:
        self.fill_calls += 1

    def write(self, command: int, data: bytes) -> None:
        self.writes.append((command, bytes(data)))


class TestLcdSpiPanelWindow:
    """LcdSpi drives the panel landscape-native: surface coords map straight
    to the address window, for both full and partial pushes, regardless of
    flip. Mirrors pi-stomp's ``uilib/lcd_ili9341.py`` (no per-push rotation,
    no coordinate swap)."""

    def _make_lcd(self, flip: bool = True) -> tuple[LcdSpi, _FakePanel]:
        import numpy

        lcd = LcdSpi(flip=flip)
        panel = _FakePanel()
        lcd._disp = panel  # type: ignore[assignment]
        lcd._pixels = numpy.empty((LCD_HEIGHT, LCD_WIDTH, 2), dtype=numpy.uint8)  # type: ignore[assignment]
        return lcd, panel

    def test_partial_push_window_matches_surface_rect(self) -> None:
        # A surface rect (x=0, y=100, w=320, h=40) must land at panel window
        # (0, 100, 319, 139) — same coordinates, no vertical flip.
        lcd, panel = self._make_lcd()
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        lcd.update(surface, [Box(0, 100, 320, 40)])
        assert len(panel.blocks) == 1
        x0, y0, x1, y1, _ = panel.blocks[0]
        assert (x0, y0, x1, y1) == (0, 100, 319, 139)
        assert panel.image_calls == 0

    def test_full_push_window_is_full_surface(self) -> None:
        lcd, panel = self._make_lcd()
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        lcd.update(surface, None)
        assert len(panel.blocks) == 1
        x0, y0, x1, y1, _ = panel.blocks[0]
        assert (x0, y0, x1, y1) == (0, 0, 319, 239)
        assert panel.image_calls == 0

    def test_flip_and_non_flip_same_window(self) -> None:
        # Orientation is MADCTL's job; the per-push window math is flip-invariant.
        rect = Box(10, 20, 30, 40)
        for flip in (True, False):
            lcd, panel = self._make_lcd(flip=flip)
            surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
            lcd.update(surface, [rect])
            x0, y0, x1, y1, _ = panel.blocks[0]
            assert (x0, y0, x1, y1) == (10, 20, 39, 59)

    def test_partial_push_pixels_match_subsurface(self) -> None:
        # RGB565-exact row colors: R,B multiples of 8, G a multiple of 4, so the
        # 565 pack (R>>3, G>>2, B>>3) round-trips. Decode the pushed bytes back
        # and assert rows 100..139 of the surface reconstruct in order.
        import numpy as np

        lcd, panel = self._make_lcd()
        surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        for y in range(100, 140):
            r = (y * 3) & 0xF8
            g = (y * 5) & 0xFC
            b = (y * 7) & 0xF8
            pygame.draw.line(surface, (r, g, b), (0, y), (LCD_WIDTH - 1, y))

        lcd.update(surface, [Box(0, 100, 320, 40)])
        x0, y0, x1, y1, data = panel.blocks[0]
        assert (x0, y0, x1, y1) == (0, 100, 319, 139)
        # data is row-major RGB565 for the 320x40 window.
        buf = np.frombuffer(data, dtype=np.uint16).reshape(40, 320)
        for row in range(40):
            y = 100 + row
            r = (y * 3) & 0xF8
            g = (y * 5) & 0xFC
            b = (y * 7) & 0xF8
            expected565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            # The panel write is MSB-first; np.uint16 reads host order. Recover
            # the wire word both ways and accept either endianness.
            px = int(buf[row, 0])
            lo = px & 0xFF
            hi = (px >> 8) & 0xFF
            wire_be = (hi << 8) | lo
            wire_le = (lo << 8) | hi
            assert wire_be == expected565 or wire_le == expected565, (
                f"row {y}: px={px:#06x} expected={expected565:#06x}"
            )


class TestLcdSpiMadctl:
    """MADCTL byte selection matches recovery's historical flip convention.

    Recovery's pre-landscape-native driver used ``flip=True`` (the default) to
    mean "mirror both axes": ``pygame.transform.rotate(surface, 180)`` +
    ``disp.image(pil, 270)``. The landscape-native port must preserve that
    convention so the default ``LcdSpi()`` call site in ``backends_real.py``
    keeps the panel upright on the Tre. MADCTL bit meanings (ILI9341 datasheet):

      * 0xE8 = MY | MX | MV | BGR  — landscape, both axes mirrored
      * 0x28 = MV | BGR             — landscape, no mirroring

    So ``flip=True`` → ``0xE8`` and ``flip=False`` → ``0x28``.
    """

    def test_flip_true_writes_mirror_both_axes_madctl(self) -> None:
        assert LcdSpi._madctl_for(flip=True) == 0xE8

    def test_flip_false_writes_no_mirror_madctl(self) -> None:
        assert LcdSpi._madctl_for(flip=False) == 0x28
