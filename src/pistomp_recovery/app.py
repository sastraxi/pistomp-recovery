"""Shared recovery application core.

`RecoveryAppCore` owns the LCD menu flow, screen stack, and event loop.
It delegates all side effects (display, input, data, services) to injected
backends via `AppBackends`.  Both the real device and the emulator construct
the same core with different backends.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import pygame

from pistomp_recovery.backends import AppBackends
from pistomp_recovery.items import Item, Row, Target
from pistomp_recovery.service import BootMode, CrashInfo
from pistomp_recovery.ui.screens import Screen
from pistomp_recovery.ui.screens.crash import CrashScreen
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.widgets.header import ICON_BACK, ICON_EXIT
from pistomp_recovery.ui.widgets.misc import InputEvent

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 0.03

MODE_CHECKPOINT: str = "checkpoint"
MODE_FACTORY: str = "factory"
MODE_UPDATES: str = "updates"

_MODE_TITLES: dict[str, str] = {
    MODE_CHECKPOINT: "Reset to Checkpoint",
    MODE_FACTORY: "Factory Reset",
    MODE_UPDATES: "Updates",
}


class RecoveryAppCore:
    """Recovery UI that works with any `AppBackends` implementation."""

    def __init__(
        self,
        backends: AppBackends,
        boot_mode: BootMode,
    ) -> None:
        self._backends: AppBackends = backends
        self._boot_mode: BootMode = boot_mode
        self._running: bool = True
        self._dirty: bool = True
        self._screen_stack: list[Screen] = []

    @property
    def surface(self) -> pygame.Surface:
        return self._backends.display.surface

    # -- lifecycle ----------------------------------------------------------

    def init(self) -> None:
        self._backends.services.stop_main_app()
        self._backends.display.init()
        self._backends.input.start()
        logger.info(
            "Recovery app initialized (boot mode: %s)",
            self._boot_mode.name,
        )

        if self._boot_mode == BootMode.CRASH_RECOVERY:
            crash_info: CrashInfo | None = self._backends.services.crash_info()
            if crash_info is None:
                crash_info = CrashInfo(
                    boot_mode=BootMode.CRASH_RECOVERY,
                    failed_service=None,
                    crash_log="",
                    service_states={},
                )
            screen: CrashScreen = CrashScreen(
                self.surface,
                on_resume=self._resume_main_app,
                on_recovery=self._show_main_menu,
                crash_info=crash_info,
            )
            self.push_screen(screen)
        else:
            self._show_main_menu()

    @property
    def running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._running = False

    def run(
        self,
        *,
        pre_poll: Callable[[], bool] | None = None,
        post_draw: Callable[[], None] | None = None,
    ) -> None:
        while self._running:
            if pre_poll is not None and not pre_poll():
                break
            events: list[InputEvent] = self._backends.input.poll()
            for event in events:
                self.handle_event(event)
            if self._dirty:
                self.draw_current_screen()
                self._backends.display.update(self.surface)
                if post_draw is not None:
                    post_draw()
                self._dirty = False
            time.sleep(POLL_INTERVAL)

    def cleanup(self) -> None:
        self._backends.input.stop()
        logger.info("Recovery app cleaned up")

    # -- screen stack -------------------------------------------------------

    def push_screen(self, screen: Screen) -> None:
        self._screen_stack.append(screen)
        self._dirty = True

    def pop_screen(self) -> None:
        if len(self._screen_stack) > 1:
            self._screen_stack.pop()
            self._dirty = True
            self._refresh_current_screen()

    def current_screen(self) -> Screen | None:
        return self._screen_stack[-1] if self._screen_stack else None

    def handle_event(self, event: InputEvent) -> None:
        screen: Screen | None = self.current_screen()
        if screen is None:
            return
        if screen.handle_event(event):
            self._dirty = True

    def draw_current_screen(self) -> None:
        screen: Screen | None = self.current_screen()
        if screen is not None:
            screen.draw()

    # -- menus --------------------------------------------------------------

    def _push_menu(
        self,
        title: str,
        rows: list[Row],
        back: bool,
        *,
        mode: str = "",
        domain: str = "",
        reload_callback: Callable[[], None] | None = None,
    ) -> MenuScreen:
        icon: Target = (
            Target(ICON_BACK, self.pop_screen)
            if back
            else Target(ICON_EXIT, self._resume_main_app)
        )
        screen: MenuScreen = MenuScreen(
            self.surface,
            title,
            rows,
            icon,
            mode=mode,
            domain=domain,
            reload_callback=reload_callback,
        )
        self.push_screen(screen)
        return screen

    def _show_main_menu(self) -> None:
        services = self._backends.services
        title: str = f"Recovery! {services.recovery_sha()}"
        rows: list[Row] = [
            Row(
                (
                    Target("Jack", services.restart_jack),
                    Target("MOD", services.restart_mod),
                ),
                prefix="Restart ",
            ),
            Row(
                (
                    Target(
                        "Reset to Checkpoint",
                        lambda: self._show_domain_picker(MODE_CHECKPOINT),
                    ),
                )
            ),
            Row(
                (
                    Target(
                        "Factory Reset",
                        lambda: self._show_domain_picker(MODE_FACTORY),
                    ),
                )
            ),
            Row(
                (
                    Target(
                        "Updates",
                        lambda: self._show_domain_picker(MODE_UPDATES),
                    ),
                )
            ),
            Row(
                (
                    Target("Reboot", services.reboot, confirm="Reboot now?"),
                    Target("Power Off", services.power_off, confirm="Power off now?"),
                )
            ),
        ]
        self._push_menu(title, rows, back=False)

    def _show_domain_picker(self, mode: str) -> None:
        rows: list[Row] = []
        for domain, label in self._backends.data.domains():
            items = self._backends.data.domain_items(mode, domain)
            count = len(items)
            has_all: bool = mode == MODE_UPDATES and bool(items) and items[-1].name == "all"
            right: str = self.badge(mode, count, all_item=has_all)
            rows.append(
                Row(
                    (Target(label, lambda m=mode, d=domain: self._show_domain(m, d)),),
                    right=right,
                )
            )
        self._push_menu(
            _MODE_TITLES[mode],
            rows,
            back=True,
            mode=mode,
            reload_callback=lambda m=mode: self._refresh_domain_picker(m),
        )

    @staticmethod
    def badge(mode: str, count: int, all_item: bool = False) -> str:
        if count == 0:
            return ""
        if mode == MODE_UPDATES and all_item:
            count = max(0, count - 1)
            if count == 0:
                return ""
        return f"{count} available" if mode == MODE_UPDATES else f"{count} changed"

    def _show_domain(self, mode: str, domain: str) -> None:
        items: list[Item] = self._backends.data.domain_items(mode, domain)
        domain_label: str = self._domain_label(domain)
        if not items:
            empty: str = "No updates" if mode == MODE_UPDATES else "Nothing to reset"
            rows: list[Row] = [Row((Target(empty, lambda: None, enabled=False),))]
        else:
            rows = [Row((self._item_target(it, mode, domain),), right=it.right) for it in items]
        self._push_menu(
            domain_label,
            rows,
            back=True,
            mode=mode,
            domain=domain,
            reload_callback=lambda m=mode, d=domain: self._refresh_domain(m, d),
        )

    def _domain_label(self, domain: str) -> str:
        for dom, label in self._backends.data.domains():
            if dom == domain:
                return label
        return domain

    def _item_target(self, item: Item, mode: str, domain: str) -> Target:
        if mode == MODE_UPDATES:
            return Target(
                item.label,
                lambda: self._install_packages([item.name]),
                confirm=f"Update {item.name}?",
            )
        if not item.actions:
            return Target(item.label, lambda: None, enabled=False)
        if len(item.actions) == 1:
            action = item.actions[0]
            return Target(
                item.label,
                self._wrap_with_refresh(action.callback, mode, domain),
                confirm=action.confirm,
            )
        return Target(
            item.label,
            lambda: self._show_item_detail(item, mode, domain),
        )

    def _wrap_with_refresh(
        self,
        callback: Callable[[], None],
        mode: str,
        domain: str,
    ) -> Callable[[], None]:
        """Run a destructive action then refresh the current domain list."""

        def _run() -> None:
            callback()
            self._refresh_domain(mode, domain)

        return _run

    def _show_item_detail(self, item: Item, mode: str, domain: str) -> None:
        rows: list[Row] = [
            Row(
                (
                    Target(
                        a.label,
                        self._wrap_with_refresh(a.callback, mode, domain),
                        confirm=a.confirm,
                    ),
                )
            )
            for a in item.actions
        ]
        self._push_menu(
            item.label,
            rows,
            back=True,
            mode=mode,
            domain=domain,
            reload_callback=lambda m=mode, d=domain: self._refresh_domain(m, d),
        )

    # -- refresh ------------------------------------------------------------

    def _refresh_current_screen(self) -> None:
        """Refresh the screen we just landed on (used after popping)."""
        screen: Screen | None = self.current_screen()
        if not isinstance(screen, MenuScreen):
            return
        if screen.mode and screen.domain:
            self._refresh_domain(screen.mode, screen.domain)
        elif screen.mode:
            self._refresh_domain_picker(screen.mode)

    def _refresh_domain(self, mode: str, domain: str) -> None:
        """Rebuild the current domain list from fresh data; pop if empty."""
        items: list[Item] = self._backends.data.domain_items(mode, domain)
        screen: Screen | None = self.current_screen()
        menu: MenuScreen | None = screen if isinstance(screen, MenuScreen) else None
        if menu is None:
            return
        if not items:
            self.pop_screen()
            self._refresh_current_screen()
            return
        rows: list[Row] = [
            Row((self._item_target(it, mode, domain),), right=it.right) for it in items
        ]
        menu.set_rows(rows)
        # Keep the parent picker badges accurate as well.
        for s in reversed(self._screen_stack[:-1]):
            if isinstance(s, MenuScreen) and s.mode == mode and not s.domain:
                self._refresh_domain_picker(mode, picker=s)
                break

    def _refresh_domain_picker(
        self,
        mode: str,
        picker: MenuScreen | None = None,
    ) -> None:
        """Refresh the domain picker so its right badges stay accurate."""
        if picker is None:
            screen: Screen | None = self.current_screen()
            if not isinstance(screen, MenuScreen):
                return
            picker = screen
        rows: list[Row] = []
        for domain, label in self._backends.data.domains():
            items = self._backends.data.domain_items(mode, domain)
            count: int = len(items)
            has_all: bool = mode == MODE_UPDATES and bool(items) and items[-1].name == "all"
            right: str = self.badge(mode, count, all_item=has_all)
            rows.append(
                Row(
                    (Target(label, lambda m=mode, d=domain: self._show_domain(m, d)),),
                    right=right,
                )
            )
        picker.set_rows(rows)

    # -- package install with progress --------------------------------------

    def _install_packages(self, packages: list[str]) -> None:
        screen: Screen | None = self.current_screen()
        menu: MenuScreen | None = screen if isinstance(screen, MenuScreen) else None

        def progress(title: str, frac: float, status: str, done: bool) -> None:
            if menu is not None:
                menu.set_progress(title, frac, status, done=done)
                self._dirty = True

        self._backends.data.install_packages(packages, progress)

    # -- exit ---------------------------------------------------------------

    def _resume_main_app(self) -> None:
        logger.info("Resuming main app")
        self._backends.services.start_main_app()
        self._running = False
