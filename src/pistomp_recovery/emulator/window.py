"""Emulator window — pygame GUI for interactive development of the recovery UI.

Layout (total 640x552):
  ┌────────────────────────┐
  │  LCD 640x480 (2x scale)│
  ├────────────────────────┤
  │  [←] [→] [Click] [Long]│
  │  ←/→ navigate | Click  │
  └────────────────────────┘

Keyboard shortcuts:
  ← / →       nav encoder left / right
  Enter        click (select)
  L            long click (back / cancel)
  Esc          quit
"""

from __future__ import annotations

from typing import Callable

import pygame

from pistomp_recovery.ui.fonts import SafeFont
from pistomp_recovery.ui.widgets.misc import InputEvent

# Dimensions
LCD_SCALE: int = 2
CTRL_H: int = 72
LCD_W: int = 320
LCD_H: int = 240

# Colours
BG = (30, 30, 30)
BTN_IDLE = (60, 60, 80)
BTN_HOVER = (80, 80, 110)
BTN_ACTIVE = (120, 120, 160)
TEXT_COLOR = (220, 220, 220)


class EmulatorWindow:
    def __init__(
        self,
        lcd_surface: pygame.Surface,
        send_event: Callable[[InputEvent], None],
    ) -> None:
        self._lcd_surface: pygame.Surface = lcd_surface
        self._send_event = send_event
        self._running: bool = True

        self.disp_w: int = LCD_W * LCD_SCALE
        self.disp_h: int = LCD_H * LCD_SCALE
        self.win_w: int = self.disp_w
        self.win_h: int = self.disp_h + CTRL_H

        self.screen: pygame.Surface = pygame.display.set_mode((self.win_w, self.win_h))
        pygame.display.set_caption("pistomp-recovery Emulator")
        self.font = SafeFont(None, 18)

        btn_y: int = self.disp_h + 8
        btn_h: int = 36
        btn_w: int = 64
        gap: int = 8
        x: int = gap

        self._buttons: list[tuple[pygame.Rect, InputEvent, str]] = []
        for _label, event in [
            ("←", InputEvent.LEFT),
            ("→", InputEvent.RIGHT),
            ("Click", InputEvent.CLICK),
            ("Long", InputEvent.LONG_CLICK),
        ]:
            rect = pygame.Rect(x, btn_y, btn_w, btn_h)
            self._buttons.append((rect, event, _label))
            x += btn_w + gap

        # Help text area
        self._help_y: int = btn_y + btn_h + 4
        self._help_font = SafeFont(None, 14)

    def process_events(self) -> bool:
        """Process pygame events. Returns False if should quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if not self._handle_key(event.key):
                    return False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)
        return True

    def _handle_key(self, key: int) -> bool:
        if key == pygame.K_ESCAPE:
            return False
        if key == pygame.K_LEFT:
            self._send_event(InputEvent.LEFT)
        elif key == pygame.K_RIGHT:
            self._send_event(InputEvent.RIGHT)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self._send_event(InputEvent.CLICK)
        elif key == pygame.K_l:
            self._send_event(InputEvent.LONG_CLICK)
        return True

    def _handle_click(self, pos: tuple[int, int]) -> None:
        for rect, event, _ in self._buttons:
            if rect.collidepoint(pos):
                self._send_event(event)
                return

    def render(self) -> None:
        self.screen.fill(BG)

        # Scale LCD surface to display size
        scaled: pygame.Surface = pygame.transform.scale(
            self._lcd_surface, (self.disp_w, self.disp_h)
        )
        self.screen.blit(scaled, (0, 0))

        # Draw buttons
        mouse_pos: tuple[int, int] = pygame.mouse.get_pos()
        for rect, _, label in self._buttons:
            hovered: bool = rect.collidepoint(mouse_pos)
            color: tuple[int, int, int] = BTN_HOVER if hovered else BTN_IDLE
            pygame.draw.rect(self.screen, color, rect, border_radius=4)
            text_surf = self.font.render(label, True, TEXT_COLOR)
            text_rect = text_surf.get_rect(center=rect.center)
            self.screen.blit(text_surf, text_rect)

        # Help line
        help_text: str = "←/→ navigate  |  Click = select  |  Long = back/cancel"
        help_surf = self._help_font.render(help_text, True, (160, 160, 160))
        self.screen.blit(help_surf, (8, self._help_y))

        pygame.display.flip()
