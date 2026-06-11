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
from pistomp_recovery.ui.widgets.menu import Menu
from pistomp_recovery.ui.widgets.misc import Box, InputEvent
from pistomp_recovery.ui.widgets.text import ProgressBar, StatusLine
from tests.conftest import FakeLcd


@pytest.fixture
def surface() -> pygame.Surface:
    return pygame.Surface((LCD_WIDTH, LCD_HEIGHT))


class TestMenuWidget:
    def test_menu_items(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        menu: Menu = Menu(Box(4, 4, 312, 232), title="Recovery")
        menu.add_item("Resume", lambda: None)
        menu.add_item("System Info", lambda: None)
        menu.add_item("Package Updates", lambda: None)
        menu.add_item("Config Management", lambda: None)
        menu.add_item("Factory Reset", lambda: None)
        menu.add_item("Reboot", lambda: None)
        menu.add_item("Power Off", lambda: None)

        surface.fill(COLORS["bg"])
        menu.draw(surface)
        fake_lcd.update(surface)
        snapshot()

    def test_menu_scroll(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        menu: Menu = Menu(Box(4, 4, 312, 100), title="Select")
        for i in range(20):
            menu.add_item(f"Item {i + 1}", lambda: None)
        for _ in range(10):
            menu.handle_event(InputEvent.RIGHT)
        for _ in range(2):
            menu.handle_event(InputEvent.LEFT)

        surface.fill(COLORS["bg"])
        menu.draw(surface)
        fake_lcd.update(surface)
        snapshot("scrolled")


class TestProgressBar:
    def test_empty_progress(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        bar: ProgressBar = ProgressBar(Box(20, 100, 280, 30))
        surface.fill(COLORS["bg"])
        bar.draw(surface)
        fake_lcd.update(surface)
        snapshot()

    def test_half_progress(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        bar: ProgressBar = ProgressBar(
            Box(20, 100, 280, 30), progress=0.5, label="Installing..."
        )
        surface.fill(COLORS["bg"])
        bar.draw(surface)
        fake_lcd.update(surface)
        snapshot()

    def test_full_progress(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        bar: ProgressBar = ProgressBar(
            Box(20, 100, 280, 30), progress=1.0, label="Complete"
        )
        surface.fill(COLORS["bg"])
        bar.draw(surface)
        fake_lcd.update(surface)
        snapshot()


class TestStatusLine:
    def test_status_text(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        status: StatusLine = StatusLine(
            Box(4, 210, 312, 22), text="3 updates available"
        )
        surface.fill(COLORS["bg"])
        status.draw(surface)
        fake_lcd.update(surface)
        snapshot()

    def test_error_status(
        self, surface: pygame.Surface, fake_lcd: FakeLcd, snapshot: Callable[..., None]
    ) -> None:
        status: StatusLine = StatusLine(
            Box(4, 210, 312, 22),
            text="Download failed",
            color=COLORS["text_error"],
        )
        surface.fill(COLORS["bg"])
        status.draw(surface)
        fake_lcd.update(surface)
        snapshot()
