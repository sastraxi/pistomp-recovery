from __future__ import annotations

from typing import Callable

import pygame

from pistomp_recovery.items import Action, Item
from pistomp_recovery.service import CrashInfo
from pistomp_recovery.ui.colors import COLORS
from pistomp_recovery.ui.fonts import SIZES, get_font
from pistomp_recovery.ui.screens import Screen
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.widgets.misc import InputEvent


class CrashScreen(Screen):
    def __init__(
        self,
        surface: pygame.Surface,
        crash_info: CrashInfo | None = None,
        on_resume: Callable[[], None] | None = None,
        on_recovery: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(surface)
        self._crash_info: CrashInfo | None = crash_info
        self._on_resume: Callable[[], None] | None = on_resume
        self._on_recovery: Callable[[], None] | None = on_recovery
        self._menu_screen: MenuScreen = MenuScreen(
            surface,
            title="Crash Recovery",
            items=[
                Item(
                    name="resume",
                    label="Resume",
                    dirty=False,
                    right="",
                    actions=[Action("Resume", self._resume)],
                ),
                Item(
                    name="recovery",
                    label="Recovery Menu",
                    dirty=False,
                    right="",
                    actions=[Action("Open", self._recovery)],
                ),
            ],
        )
        self._menu_screen.set_back_callback(None)

    def _resume(self) -> None:
        if self._on_resume:
            self._on_resume()

    def _recovery(self) -> None:
        if self._on_recovery:
            self._on_recovery()

    def draw(self) -> None:
        self._surface.fill(COLORS["bg"])

        title_font = get_font(SIZES["title"])
        title_surf: pygame.Surface = title_font.render(
            "Crash Recovery", True, COLORS["text_error"]
        )
        title_rect: pygame.Rect = title_surf.get_rect(centerx=160, y=8)
        self._surface.blit(title_surf, title_rect)

        if self._crash_info is not None:
            svc_font = get_font(SIZES["small"])
            y: int = 32
            for svc, state in self._crash_info.service_states.items():
                color = COLORS["text_error"] if state == "failed" else COLORS["text_dim"]
                marker: str = " \u2190" if state == "failed" else ""
                line: str = f"  {svc}: {state}{marker}"
                surf: pygame.Surface = svc_font.render(line, True, color)
                self._surface.blit(surf, (10, y))
                y += 16

            if self._crash_info.crash_log:
                y += 4
                log_font = get_font(SIZES["small"])
                lines: list[str] = self._crash_info.crash_log.split("\n")[-4:]
                for line in lines:
                    if y > 100:
                        break
                    log_surf: pygame.Surface = log_font.render(
                        line[:48], True, COLORS["text_dim"]
                    )
                    self._surface.blit(log_surf, (10, y))
                    y += 14

        self._menu_screen.draw()

    def handle_event(self, event: InputEvent) -> bool:
        return self._menu_screen.handle_event(event)

    def set_back_callback(self, callback: Callable[[], None] | None) -> None:
        self._on_back = callback
        self._menu_screen.set_back_callback(None)
