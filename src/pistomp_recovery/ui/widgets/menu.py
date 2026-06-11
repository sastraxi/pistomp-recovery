from __future__ import annotations

from typing import Callable

import pygame

from pistomp_recovery.ui.colors import COLORS
from pistomp_recovery.ui.fonts import get_font
from pistomp_recovery.ui.widgets.misc import Box, InputEvent

ITEM_HEIGHT: int = 22
MARGIN: int = 4
RIGHT_COL_PAD: int = 8

MenuItem = tuple[str, Callable[[], None], str]


class Menu:
    def __init__(self, bounds: Box, title: str = "") -> None:
        self.bounds: Box = bounds
        self.title: str = title
        self.items: list[MenuItem] = []
        self.sel_index: int = 0
        self.scroll_offset: int = 0
        self._right_col_width: int = 0

    def add_item(
        self, label: str, callback: Callable[[], None], right: str = ""
    ) -> None:
        self.items.append((label, callback, right))
        self._recalc_right_col()

    def clear_items(self) -> None:
        self.items.clear()
        self.sel_index = 0
        self.scroll_offset = 0
        self._right_col_width = 0

    def _recalc_right_col(self) -> None:
        if not self.items:
            self._right_col_width = 0
            return
        font = get_font(20)
        max_w: int = 0
        for _, _, right in self.items:
            if right:
                surf: pygame.Surface = font.render(right, True, (255, 255, 255))
                max_w = max(max_w, surf.get_width())
        self._right_col_width = max_w + RIGHT_COL_PAD if max_w > 0 else 0

    @property
    def visible_count(self) -> int:
        title_h: int = 20 if self.title else 0
        content_h: int = self.bounds.h - title_h
        return max(1, content_h // ITEM_HEIGHT)

    def handle_event(self, event: InputEvent) -> bool:
        if not self.items:
            return False

        if event == InputEvent.LEFT:
            self.sel_index = (self.sel_index - 1) % len(self.items)
            self._scroll_into_view()
            return True
        elif event == InputEvent.RIGHT:
            self.sel_index = (self.sel_index + 1) % len(self.items)
            self._scroll_into_view()
            return True
        elif event == InputEvent.CLICK:
            if 0 <= self.sel_index < len(self.items):
                _, callback, _ = self.items[self.sel_index]
                callback()
                return True
        return False

    def _scroll_into_view(self) -> None:
        if self.sel_index < self.scroll_offset:
            self.scroll_offset = self.sel_index
        elif self.sel_index >= self.scroll_offset + self.visible_count:
            self.scroll_offset = self.sel_index - self.visible_count + 1

    def draw(self, surface: pygame.Surface) -> None:
        title_h: int = 20 if self.title else 0
        y_start: int = self.bounds.y + title_h
        x_start: int = self.bounds.x + MARGIN
        font = get_font(20)
        small_font = get_font(16)

        end: int = min(self.scroll_offset + self.visible_count, len(self.items))
        for i in range(self.scroll_offset, end):
            y: int = y_start + (i - self.scroll_offset) * ITEM_HEIGHT
            label: str = self.items[i][0]
            right_text: str = self.items[i][2]
            is_selected: bool = i == self.sel_index

            if is_selected:
                sel_rect: pygame.Rect = pygame.Rect(
                    self.bounds.x + 2, y, self.bounds.w - 4, ITEM_HEIGHT
                )
                pygame.draw.rect(surface, COLORS["selection_bg"], sel_rect, border_radius=3)

            text_color = (
                COLORS["text_bright"] if is_selected else COLORS["text_dim"]
            )
            right_color = (
                COLORS["text_accent"] if is_selected else COLORS["text_dim"]
            )

            label_max_w: int = self.bounds.w - MARGIN * 2 - 4
            if self._right_col_width > 0:
                label_max_w -= self._right_col_width

            text_surf: pygame.Surface = font.render(label, True, text_color)
            text_rect: pygame.Rect = text_surf.get_rect(
                midleft=(x_start, y + ITEM_HEIGHT // 2)
            )

            if self._right_col_width > 0:
                clip_rect: pygame.Rect = pygame.Rect(
                    x_start, y, label_max_w, ITEM_HEIGHT
                )
                surface.set_clip(clip_rect)
                surface.blit(text_surf, text_rect)
                surface.set_clip(None)
            else:
                surface.blit(text_surf, text_rect)

            if right_text:
                right_surf: pygame.Surface = small_font.render(right_text, True, right_color)
                right_x: int = self.bounds.right - self._right_col_width + RIGHT_COL_PAD
                right_rect: pygame.Rect = right_surf.get_rect(
                    midleft=(right_x, y + ITEM_HEIGHT // 2)
                )
                surface.blit(right_surf, right_rect)

        if len(self.items) > self.visible_count:
            total: int = len(self.items)
            vis: int = self.visible_count
            bar_h: int = max(8, int(y_start + vis * ITEM_HEIGHT * vis / total))
            max_offset: int = max(1, total - vis)
            bar_y: int = y_start + int(
                (vis * ITEM_HEIGHT - bar_h) * self.scroll_offset / max_offset
            )
            scroll_rect: pygame.Rect = pygame.Rect(self.bounds.right - 4, bar_y, 2, bar_h)
            pygame.draw.rect(surface, COLORS["scroll_thumb"], scroll_rect)
