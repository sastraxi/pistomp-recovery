from __future__ import annotations

import pygame

from pistomp_recovery.ui.colors import COLORS
from pistomp_recovery.ui.fonts import SafeFont, get_font
from pistomp_recovery.ui.widgets.misc import Box


class ProgressBar:
    def __init__(
        self, bounds: Box, progress: float = 0.0, label: str = ""
    ) -> None:
        self.bounds: Box = bounds
        self.progress: float = progress
        self.label: str = label

    def set_progress(self, progress: float, label: str = "") -> None:
        self.progress = max(0.0, min(1.0, progress))
        if label:
            self.label = label

    def draw(self, surface: pygame.Surface) -> None:
        rect: pygame.Rect = pygame.Rect(
            self.bounds.x, self.bounds.y, self.bounds.w, self.bounds.h
        )

        pygame.draw.rect(surface, COLORS["progress_bg"], rect, border_radius=3)

        if self.progress > 0:
            fill_w: int = max(1, int(self.bounds.w * self.progress))
            fill_rect: pygame.Rect = pygame.Rect(
                self.bounds.x, self.bounds.y, fill_w, self.bounds.h
            )
            pygame.draw.rect(surface, COLORS["progress_fg"], fill_rect, border_radius=3)

        if self.label:
            font: SafeFont = get_font(18)
            label_surf: pygame.Surface = font.render(
                self.label, True, COLORS["text_bright"]
            )
            label_rect: pygame.Rect = label_surf.get_rect(center=rect.center)
            surface.blit(label_surf, label_rect)


class StatusLine:
    def __init__(
        self, bounds: Box, text: str = "",
        color: tuple[int, int, int] | tuple[int, int, int, int] | None = None
    ) -> None:
        self.bounds: Box = bounds
        self.text: str = text
        self.color: tuple[int, int, int] | tuple[int, int, int, int] = color or COLORS["text_dim"]

    def set_text(
        self, text: str, color: tuple[int, int, int] | tuple[int, int, int, int] | None = None
    ) -> None:
        self.text = text
        if color is not None:
            self.color = color

    def draw(self, surface: pygame.Surface) -> None:
        if not self.text:
            return
        font: SafeFont = get_font(18)
        text_surf: pygame.Surface = font.render(self.text, True, self.color)
        text_rect: pygame.Rect = text_surf.get_rect(
            midleft=(self.bounds.x + 4, self.bounds.y + self.bounds.h // 2)
        )
        surface.blit(text_surf, text_rect)
