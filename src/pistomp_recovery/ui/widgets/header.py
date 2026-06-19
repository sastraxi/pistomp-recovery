from __future__ import annotations

import pygame

from pistomp_recovery.constants import LCD_WIDTH
from pistomp_recovery.ui.colors import COLORS
from pistomp_recovery.ui.fonts import TEXT_DY, cell_size, get_font, text_width

#: Glyphs for the header's top-right action icon (CP437-native).
ICON_BACK: str = "← Back"
ICON_EXIT: str = "♫ Exit"


def header_height() -> int:
    return cell_size()[1]


class Header:
    """Inverted title bar with a selectable back/exit icon at top-right.

    The icon itself is a navigable target owned by the screen; the screen
    passes ``icon_selected`` so the header can draw the reticule. When selected
    the icon flips to a blue box (the page background) with light text so it
    still stands out against the light title bar.
    """

    def __init__(self, title: str, icon: str) -> None:
        self.title: str = title
        self.icon: str = icon

    def draw(self, surface: pygame.Surface, icon_selected: bool) -> None:
        cw, ch = cell_size()
        bar: pygame.Rect = pygame.Rect(0, 0, LCD_WIDTH, ch)
        surface.fill(COLORS["title_bg"], bar)

        font = get_font()
        title_surf: pygame.Surface = font.render(self.title, True, COLORS["title_fg"])
        surface.blit(title_surf, (cw, (ch - title_surf.get_height()) // 2 + TEXT_DY))

        icon_w: int = text_width(self.icon)
        icon_x: int = LCD_WIDTH - icon_w - cw
        if icon_selected:
            pad: int = 2
            box: pygame.Rect = pygame.Rect(
                icon_x - pad, 0, icon_w + pad * 2, ch
            )
            surface.fill(COLORS["bg"], box)
            icon_surf: pygame.Surface = font.render(self.icon, True, COLORS["text"])
        else:
            icon_surf = font.render(self.icon, True, COLORS["title_fg"])
        surface.blit(icon_surf, (icon_x, (ch - icon_surf.get_height()) // 2 + TEXT_DY))
