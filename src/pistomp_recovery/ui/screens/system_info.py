from __future__ import annotations

import pygame

from pistomp_recovery.service import get_system_info
from pistomp_recovery.ui.colors import COLORS
from pistomp_recovery.ui.fonts import SIZES, get_font
from pistomp_recovery.ui.screens import Screen
from pistomp_recovery.ui.widgets.misc import InputEvent


class SystemInfoScreen(Screen):
    def __init__(self, surface: pygame.Surface) -> None:
        super().__init__(surface)
        self._info: dict[str, str] = {}

    def refresh(self) -> None:
        self._info = get_system_info()

    def draw(self) -> None:
        self._surface.fill(COLORS["bg"])

        title_font = get_font(SIZES["heading"])
        title_surf: pygame.Surface = title_font.render(
            "System Info", True, COLORS["text_bright"]
        )
        self._surface.blit(title_surf, (10, 8))

        y: int = 36
        body_font = get_font(SIZES["body"])
        items: list[tuple[str, str]] = list(self._info.items())
        for key, value in items[:10]:
            label: str = f"{key}: "
            label_surf: pygame.Surface = body_font.render(
                label, True, COLORS["text_dim"]
            )
            value_surf: pygame.Surface = body_font.render(
                value, True, COLORS["text_bright"]
            )
            self._surface.blit(label_surf, (10, y))
            self._surface.blit(value_surf, (10 + label_surf.get_width(), y))
            y += 20

        y = max(y + 10, 200)
        back_font = get_font(SIZES["small"])
        back_surf: pygame.Surface = back_font.render(
            "\u2190 Long-press back", True, COLORS["text_dim"]
        )
        self._surface.blit(back_surf, (10, y))

    def handle_event(self, event: InputEvent) -> bool:
        if event == InputEvent.LONG_CLICK:
            self._go_back()
            return True
        return False
