from __future__ import annotations

from typing import Callable

import pygame

from pistomp_recovery.ui.colors import COLORS, ColorName
from pistomp_recovery.ui.fonts import SIZES, get_font
from pistomp_recovery.ui.widgets.misc import InputEvent

DIALOG_W: int = 260
DIALOG_H: int = 100
BORDER_RADIUS: int = 8


class ConfirmDialog:
    def __init__(
        self,
        surface: pygame.Surface,
        title: str,
        on_confirm: Callable[[], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._surface: pygame.Surface = surface
        self._title: str = title
        self._on_confirm: Callable[[], None] = on_confirm
        self._on_cancel: Callable[[], None] = on_cancel
        self._confirmed: bool = False
        self._cancelled: bool = False

    def handle_event(self, event: InputEvent) -> bool:
        if event == InputEvent.LEFT:
            self._confirmed = False
            self._cancelled = False
            return True
        elif event == InputEvent.RIGHT:
            self._confirmed = True
            return True
        elif event == InputEvent.CLICK:
            if self._confirmed:
                self._on_confirm()
            else:
                self._on_cancel()
            return True
        elif event == InputEvent.LONG_CLICK:
            self._on_cancel()
            return True
        return False

    def draw(self) -> None:
        self._surface.fill(
            COLORS["overlay"], special_flags=pygame.BLEND_RGBA_MULT
        )

        x: int = (320 - DIALOG_W) // 2
        y: int = (240 - DIALOG_H) // 2
        dialog_rect: pygame.Rect = pygame.Rect(x, y, DIALOG_W, DIALOG_H)

        pygame.draw.rect(
            self._surface, COLORS["panel_bg"], dialog_rect,
            border_radius=BORDER_RADIUS,
        )
        pygame.draw.rect(
            self._surface, COLORS["panel_border"], dialog_rect,
            width=1, border_radius=BORDER_RADIUS,
        )

        title_font = get_font(SIZES["heading"])
        lines: list[str] = self._title.split("\n")
        line_y: int = y + 16
        for line in lines:
            surf: pygame.Surface = title_font.render(
                line, True, COLORS["text_bright"]
            )
            rect: pygame.Rect = surf.get_rect(centerx=160, y=line_y)
            self._surface.blit(surf, rect)
            line_y += 22

        btn_w: int = 90
        btn_h: int = 30
        btn_y: int = y + DIALOG_H - btn_h - 12
        cancel_rect: pygame.Rect = pygame.Rect(
            x + 20, btn_y, btn_w, btn_h
        )
        confirm_rect: pygame.Rect = pygame.Rect(
            x + DIALOG_W - btn_w - 20, btn_y, btn_w, btn_h
        )

        btn_font = get_font(SIZES["body"])
        cancel_color: ColorName = (
            "text_dim" if not self._confirmed else "text_bright"
        )
        confirm_color: ColorName = (
            "text_bright" if self._confirmed else "text_dim"
        )
        buttons: list[tuple[pygame.Rect, str, bool, ColorName]] = [
            (cancel_rect, "Cancel", not self._confirmed, cancel_color),
            (confirm_rect, "Confirm", self._confirmed, confirm_color),
        ]
        for rect, label, is_sel, color_key in buttons:
            bg = (
                COLORS["selection_bg"] if is_sel else COLORS["progress_bg"]
            )
            pygame.draw.rect(self._surface, bg, rect, border_radius=4)
            text_surf: pygame.Surface = btn_font.render(
                label, True, COLORS[color_key]
            )
            text_rect: pygame.Rect = text_surf.get_rect(center=rect.center)
            self._surface.blit(text_surf, text_rect)
