from __future__ import annotations

from typing import Callable

import pygame

from pistomp_recovery.constants import LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.ui.colors import COLORS, ColorName
from pistomp_recovery.ui.fonts import TEXT_DY, cell_size, get_font, text_width
from pistomp_recovery.ui.widgets.misc import InputEvent

_MAX_W: int = 304
_AIM_W: int = 224
_PAD: int = 8
_BORDER: int = 4


class ConfirmDialog:
    """Modal overlay with No/Yes choices, rendered in the QBASIC style.

    Text is word-wrapped aiming for ``_AIM_W`` box width, but the box
    expands to fit the longest line (capped at ``_MAX_W``) so single-word
    pedalboard names don't wrap unnecessarily.  Height auto-sizes to
    content with the buttons flush below the text.  The focused choice
    is drawn in reverse video.  Intercepts all input until dismissed.
    Encoder rotates between No and Yes; click activates.
    """

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
        self._lines: list[str] = []
        self._width: int = _AIM_W
        self._wrap()

    def _wrap(self) -> None:
        cw: int = cell_size()[0]
        aim_chars: int = (_AIM_W - _PAD * 2 - _BORDER * 2) // cw
        self._lines = []
        for paragraph in self._title.split("\n"):
            words: list[str] = paragraph.split(" ")
            line: list[str] = []
            for word in words:
                if sum(len(w) for w in line) + len(line) + len(word) > aim_chars:
                    self._lines.append(" ".join(line))
                    line = [word]
                else:
                    line.append(word)
            if line:
                self._lines.append(" ".join(line))
        if not self._lines:
            self._lines = [""]

        longest: int = max(len(l) for l in self._lines) if self._lines else 0
        needed: int = longest * cw + _PAD * 2 + _BORDER * 2
        self._width = min(_MAX_W, max(_AIM_W, needed))

    def _height(self) -> int:
        ch: int = cell_size()[1]
        n: int = len(self._lines)
        return _PAD * 2 + _BORDER * 2 + ch * n + ch * 2

    def handle_event(self, event: InputEvent) -> bool:
        if event in (InputEvent.LEFT, InputEvent.RIGHT):
            self._confirmed = not self._confirmed
            return True
        if event == InputEvent.CLICK:
            if self._confirmed:
                self._on_confirm()
            else:
                self._on_cancel()
            return True
        return False

    def draw(self) -> None:
        overlay: pygame.Surface = pygame.Surface(
            (LCD_WIDTH, LCD_HEIGHT), pygame.SRCALPHA
        )
        overlay.fill(COLORS["overlay"])
        self._surface.blit(overlay, (0, 0))

        ch: int = cell_size()[1]
        h: int = self._height()
        w: int = self._width
        x: int = (LCD_WIDTH - w) // 2
        y: int = (LCD_HEIGHT - h) // 2
        rect: pygame.Rect = pygame.Rect(x, y, w, h)
        self._surface.fill(COLORS["bg"], rect)
        pygame.draw.rect(self._surface, COLORS["text"], rect, width=1)
        pygame.draw.rect(
            self._surface, COLORS["text"],
            pygame.Rect(x + 2, y + 2, w - 4, h - 4), width=1,
        )

        font = get_font()
        line_y: int = y + _PAD + _BORDER
        for line in self._lines:
            surf: pygame.Surface = font.render(line, True, COLORS["text"])
            self._surface.blit(
                surf, (LCD_WIDTH // 2 - surf.get_width() // 2, line_y + TEXT_DY)
            )
            line_y += ch

        btn_y: int = y + h - _PAD - _BORDER - ch
        self._draw_button("No", LCD_WIDTH // 2 - w // 4, btn_y, not self._confirmed)
        self._draw_button("Yes", LCD_WIDTH // 2 + w // 4, btn_y, self._confirmed)

    def _draw_button(self, label: str, cx: int, y: int, selected: bool) -> None:
        cw, ch = cell_size()
        font = get_font()
        t_w: int = text_width(label)
        x: int = cx - t_w // 2
        fg: ColorName = "sel_fg" if selected else "text"
        if selected:
            box: pygame.Rect = pygame.Rect(x - cw, y, t_w + cw * 2, ch)
            self._surface.fill(COLORS["sel_bg"], box)
        surf: pygame.Surface = font.render(label, True, COLORS[fg])
        self._surface.blit(surf, (x, y + TEXT_DY))
