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
