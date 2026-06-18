"""Widget snapshot tests for pistomp-recovery.

Each test draws a widget arrangement and asserts the output matches
a stored PNG snapshot. Run with --snapshot-update to regenerate.
"""

from __future__ import annotations

from typing import Callable

import pygame
import pytest

from pistomp_recovery.constants import LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.ui.colors import COLORS
from pistomp_recovery.ui.widgets.confirm_dialog import ConfirmDialog
from pistomp_recovery.ui.widgets.header import ICON_BACK, ICON_EXIT, Header
from pistomp_recovery.ui.widgets.misc import Box
from pistomp_recovery.ui.widgets.text import ProgressBar, StatusLine
from tests.conftest import FakeLcd


@pytest.fixture
def surface() -> pygame.Surface:
    return pygame.Surface((LCD_WIDTH, LCD_HEIGHT))


class TestHeader:
    def test_exit_icon_unselected(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        surface.fill(COLORS["bg"])
        Header("Recovery! abc1234", ICON_EXIT).draw(surface, icon_selected=False)
        fake_lcd.update(surface)
        snapshot()

    def test_back_icon_selected(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        surface.fill(COLORS["bg"])
        Header("Pedalboards", ICON_BACK).draw(surface, icon_selected=True)
        fake_lcd.update(surface)
        snapshot()


class TestProgressBar:
    def test_empty_progress(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        bar: ProgressBar = ProgressBar(Box(16, 112, 288, 16))
        surface.fill(COLORS["bg"])
        bar.draw(surface)
        fake_lcd.update(surface)
        snapshot()

    def test_half_progress(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        bar: ProgressBar = ProgressBar(Box(16, 112, 288, 16), progress=0.5, label="Installing...")
        surface.fill(COLORS["bg"])
        bar.draw(surface)
        fake_lcd.update(surface)
        snapshot()

    def test_full_progress(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        bar: ProgressBar = ProgressBar(Box(16, 112, 288, 16), progress=1.0, label="Complete")
        surface.fill(COLORS["bg"])
        bar.draw(surface)
        fake_lcd.update(surface)
        snapshot()


class TestStatusLine:
    def test_status_text(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        status: StatusLine = StatusLine(Box(0, 224, LCD_WIDTH, 16), text="3 updates available")
        surface.fill(COLORS["bg"])
        status.draw(surface)
        fake_lcd.update(surface)
        snapshot()

    def test_error_status(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        status: StatusLine = StatusLine(
            Box(0, 224, LCD_WIDTH, 16),
            text="Download failed",
            color=COLORS["error"],
        )
        surface.fill(COLORS["bg"])
        status.draw(surface)
        fake_lcd.update(surface)
        snapshot()


class TestConfirmDialog:
    def test_short_name(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        surface.fill(COLORS["bg"])
        dialog = ConfirmDialog(surface, "Reset jackdrc\nto factory?", lambda: None, lambda: None)
        dialog.draw()
        fake_lcd.update(surface)
        snapshot()

    def test_long_name_wraps(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        surface.fill(COLORS["bg"])
        dialog = ConfirmDialog(
            surface,
            "Rollback My-Very-Long-Pedalboard-Name\n to last stamp?",
            lambda: None, lambda: None,
        )
        dialog.draw()
        fake_lcd.update(surface)
        snapshot()
