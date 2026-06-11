from __future__ import annotations

from typing import Callable

import pygame

from pistomp_recovery.items import Action, Item
from pistomp_recovery.ui.colors import COLORS
from pistomp_recovery.ui.fonts import SIZES, get_font
from pistomp_recovery.ui.screens import Screen
from pistomp_recovery.ui.widgets.confirm_dialog import ConfirmDialog
from pistomp_recovery.ui.widgets.menu import Menu
from pistomp_recovery.ui.widgets.misc import Box, InputEvent
from pistomp_recovery.ui.widgets.text import ProgressBar, StatusLine


class MenuScreen(Screen):
    def __init__(
        self,
        surface: pygame.Surface,
        title: str,
        items: list[Item],
        back_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(surface)
        self._title: str = title
        self._items: list[Item] = items
        self._on_back: Callable[[], None] | None = back_callback
        self._state: str = "LIST"
        self._detail_item: Item | None = None
        self._confirm_action: Action | None = None
        self._confirm_dialog: ConfirmDialog | None = None
        self._menu: Menu = Menu(Box(4, 24, 312, 180), title=title)
        self._progress_bar: ProgressBar = ProgressBar(Box(20, 80, 280, 30))
        self._status: StatusLine = StatusLine(Box(4, 210, 312, 22))
        self._progress_title: str = ""
        self._build_list()

    def set_items(self, items: list[Item]) -> None:
        self._items = items
        if self._state == "LIST":
            self._build_list()

    def _build_list(self) -> None:
        self._menu.clear_items()
        for item in self._items:
            label: str = item.label + (" *" if item.dirty else "")
            self._menu.add_item(
                label, lambda i=item: self._show_detail(i), item.right
            )
        if self._on_back is not None:
            self._menu.add_item("\u2190 Back", self._go_back)

    def _show_detail(self, item: Item) -> None:
        # Skip the detail screen when there's a single no-confirm action.
        if len(item.actions) == 1 and item.actions[0].confirm is None:
            item.actions[0].callback()
            return
        self._detail_item = item
        self._state = "DETAIL"
        self._menu.clear_items()
        for action in item.actions:
            self._menu.add_item(
                action.label, lambda a=action: self._run_action(a)
            )
        self._menu.add_item("\u2190 Back", self._back_to_list)
        self._confirm_dialog = None

    def _run_action(self, action: Action) -> None:
        if action.confirm:
            self._confirm_action = action
            self._state = "CONFIRM"
            self._confirm_dialog = ConfirmDialog(
                self._surface,
                action.confirm,
                self._do_confirm,
                self._cancel_confirm,
            )
        else:
            action.callback()

    def _back_to_list(self) -> None:
        self._detail_item = None
        self._state = "LIST"
        self._confirm_dialog = None
        self._build_list()

    def _cancel_confirm(self) -> None:
        self._state = "DETAIL"
        self._confirm_action = None
        self._confirm_dialog = None

    def _do_confirm(self) -> None:
        if self._confirm_action is not None:
            self._confirm_action.callback()
        self._state = "DETAIL"
        self._confirm_action = None
        self._confirm_dialog = None

    def set_progress(self, title: str, progress: float, status: str) -> None:
        self._state = "PROGRESS"
        self._progress_title = title
        self._progress_bar.set_progress(progress)
        self._status.set_text(status)

    def clear_progress(self) -> None:
        self._state = "LIST"
        self._detail_item = None
        self._build_list()

    def set_status(self, text: str, color: tuple[int, int, int] | None = None) -> None:
        if color is not None:
            self._status.set_text(text, color)
        else:
            self._status.set_text(text)

    def draw(self) -> None:
        self._surface.fill(COLORS["bg"])

        if self._state == "PROGRESS":
            title_font = get_font(SIZES["title"])
            title_surf: pygame.Surface = title_font.render(
                self._progress_title, True, COLORS["text_bright"]
            )
            title_rect: pygame.Rect = title_surf.get_rect(centerx=160, y=30)
            self._surface.blit(title_surf, title_rect)
            self._progress_bar.draw(self._surface)
            self._status.draw(self._surface)
            return

        if self._state == "CONFIRM":
            self._menu.draw(self._surface)
            self._status.draw(self._surface)
            if self._confirm_dialog is not None:
                self._confirm_dialog.draw()
            return

        self._menu.draw(self._surface)
        self._status.draw(self._surface)

    def handle_event(self, event: InputEvent) -> bool:
        if self._state == "PROGRESS":
            # Block all input during progress operations (download/install).
            # Prevents accidental back navigation / pop-screen.
            return True

        if self._state == "CONFIRM":
            if self._confirm_dialog is not None:
                return self._confirm_dialog.handle_event(event)
            return True

        if event == InputEvent.LONG_CLICK:
            if self._state == "DETAIL":
                self._back_to_list()
                return True
            if self._state == "LIST" and self._on_back is not None:
                self._on_back()
                return True
            return False

        return self._menu.handle_event(event)
