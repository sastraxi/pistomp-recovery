"""Shared recovery application core.

`RecoveryAppCore` owns the LCD menu flow, screen stack, and event loop.
It delegates all side effects (display, input, data, services) to injected
backends via `AppBackends`.  Both the real device and the emulator construct
the same core with different backends.
"""

from __future__ import annotations

import logging
import textwrap
import threading
import time
from typing import Callable

import pygame

from pistomp_recovery.backends import AppBackends
from pistomp_recovery.constants import DOMAIN_PLUGINS, DOMAIN_SYSTEM, LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.items import Item, Row, Target
from pistomp_recovery.service import BootMode, CrashInfo
from pistomp_recovery.ui.screens import Screen
from pistomp_recovery.ui.screens.crash import CrashScreen
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.widgets.header import ICON_BACK, ICON_EXIT
from pistomp_recovery.ui.widgets.misc import Box, InputEvent
from pistomp_recovery.util import human_size

_RESTART_MAX_COLS: int = 38

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 0.03

# Dirty clips whose estimated SPI transfer time is at or below this budget are
# pushed inline (one push per change, e.g. a selection scan). Larger clips
# coalesce into a single deferred flush on the next poll tick. Mirrors
# pi-stomp's PanelStack.INLINE_BUDGET_MS.
INLINE_BUDGET_MS: float = 8.0

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
        crash_info: CrashInfo,
    ) -> None:
        self._backends: AppBackends = backends
        self._crash_info: CrashInfo = crash_info
        self._boot_mode: BootMode = crash_info.boot_mode
        self._running: bool = True
        # Dirty-rect state mirrors pi-stomp's PanelStack:
        #   _lcd_needs_update=False            → clean, nothing to push
        #   _lcd_needs_update=True, clip=None  → full-screen redraw pending
        #   _lcd_needs_update=True, clip=Box   → coalesced partial push pending
        # Starts full-screen-pending so the first frame draws.
        self._lcd_needs_update: bool = True
        self._pending_lcd_clip: Box | None = None
        # Rects pushed inline this tick (drawn + sent to display immediately).
        # Collected so _flush_dirty can pass them to post_draw even when there
        # is no deferred clip.
        self._inline_rects: list[Box] = []
        self._screen_stack: list[Screen] = []

    def _mark_dirty(self, rect: Box | None = None) -> None:
        """Draw a dirty region and push inline or coalesce for the next tick."""
        if rect is None or (self._lcd_needs_update and self._pending_lcd_clip is None):
            # Full-screen pending (push/pop/thread) — always deferred.
            self._pending_lcd_clip = None
            self._lcd_needs_update = True
            return

        if rect.is_empty():
            return

        # Draw just this clip now; the surface stays authoritative.
        self.draw_current_screen(rect)

        if self._backends.display.transfer_ms(rect) <= INLINE_BUDGET_MS:
            self._backends.display.update(self.surface, [rect])
            self._inline_rects.append(rect)
            return

        # Coalesce into the pending push.
        if self._pending_lcd_clip is None:
            self._pending_lcd_clip = rect
        else:
            self._pending_lcd_clip = self._pending_lcd_clip.union(rect)
        self._lcd_needs_update = True

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
            screen: CrashScreen = CrashScreen(
                self.surface,
                on_resume=self._resume_main_app,
                on_recovery=self._show_main_menu,
                crash_info=self._crash_info,
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
        post_draw: Callable[[list[Box]], None] | None = None,
    ) -> None:
        while self._running:
            if pre_poll is not None and not pre_poll():
                break
            events: list[InputEvent] = self._backends.input.poll()
            for event in events:
                self.handle_event(event)
            self._flush_dirty(post_draw)
            time.sleep(POLL_INTERVAL)

    def _flush_dirty(self, post_draw: Callable[[list[Box]], None] | None = None) -> None:
        """Flush any coalesced or full-screen pending push to the display.

        Mirrors pi-stomp's ``PanelStack.poll_updates`` + ``_flush_lcd``.
        Inline pushes already happened in ``_mark_dirty``; this handles the
        deferred path. Also collects all rects pushed this tick and hands
        them to ``post_draw`` so the emulator window can partial-flip.
        """
        inline = self._inline_rects
        self._inline_rects = []

        if not self._lcd_needs_update:
            if inline and post_draw is not None:
                post_draw(inline)
            return

        clip = self._pending_lcd_clip
        self._pending_lcd_clip = None
        self._lcd_needs_update = False

        if clip is None:
            # Full-screen: draw now (push/pop/thread didn't draw at dirty time).
            full = Box(0, 0, LCD_WIDTH, LCD_HEIGHT)
            self.draw_current_screen(full)
            self._backends.display.update(self.surface, [full])
            if post_draw is not None:
                post_draw([full])
        else:
            # Coalesced rect: surface already drawn, just push.
            self._backends.display.update(self.surface, [clip])
            if post_draw is not None:
                post_draw(inline + [clip])

    def cleanup(self) -> None:
        self._backends.input.stop()
        logger.info("Recovery app cleaned up")

    # -- screen stack -------------------------------------------------------

    def push_screen(self, screen: Screen) -> None:
        self._screen_stack.append(screen)
        self._mark_dirty(None)

    def pop_screen(self) -> None:
        if len(self._screen_stack) > 1:
            self._screen_stack.pop()
            self._mark_dirty(None)
            self._refresh_current_screen()

    def current_screen(self) -> Screen | None:
        return self._screen_stack[-1] if self._screen_stack else None

    def handle_event(self, event: InputEvent) -> None:
        screen: Screen | None = self.current_screen()
        if screen is None:
            return
        touched: list[Box] = screen.handle_event(event)
        for rect in touched:
            self._mark_dirty(rect)

    def draw_current_screen(self, clip: Box | None = None) -> None:
        screen: Screen | None = self.current_screen()
        if screen is not None:
            screen.draw(clip)

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

    def _build_main_menu_rows(
        self,
        unverified: tuple[str, ...] = (),
    ) -> list[Row]:
        services = self._backends.services
        rows: list[Row] = [
            Row(
                (
                    Target(
                        "Restart Jack",
                        lambda: self._restart_service("Jack", ["jack"], services.restart_jack),
                    ),
                )
            ),
            Row(
                (
                    Target(
                        "Restart MOD",
                        lambda: self._restart_service("MOD", ["mod-host"], services.restart_mod),
                    ),
                )
            ),
            Row(prefix="---", separator=True),
            Row((Target("Updates", self._show_updates_menu),)),
        ]
        if unverified:
            n = len(unverified)
            label = f"{n} package{'s' if n != 1 else ''} unverified"
            rows.append(Row((Target(label, lambda u=unverified: self._show_unverified_menu(u)),)))
        rows += [
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
            Row(prefix="---", separator=True),
            Row((Target("Reboot", services.reboot, confirm="Reboot now?"),)),
            Row((Target("Power Off", services.power_off, confirm="Power off now?"),)),
        ]
        return rows

    def _show_main_menu(self) -> None:
        services = self._backends.services
        title: str = f"Recovery! {services.recovery_sha()}"
        menu = self._push_menu(title, self._build_main_menu_rows(), back=False)

        def _check() -> None:
            unverified = self._backends.data.unverified_packages()
            if unverified:
                menu.set_rows(self._build_main_menu_rows(unverified))
                self._mark_dirty(None)

        threading.Thread(target=_check, daemon=True).start()

    def _show_unverified_menu(self, unverified: tuple[str, ...]) -> None:
        rows: list[Row] = [Row(prefix=name) for name in unverified]
        self._push_menu("Unverified Packages", rows, back=True)

    def _show_domain_picker(self, mode: str) -> None:
        rows: list[Row] = []
        for domain, label in self._backends.data.domains(mode):
            if mode == MODE_FACTORY and domain == DOMAIN_PLUGINS:
                summary = self._backends.data.domain_summary(mode, domain)
                rows.append(
                    Row(
                        (Target(label, self._show_factory_plugins_menu),),
                        right=summary,
                    )
                )
                continue
            items = self._backends.data.domain_items(mode, domain)
            count = sum(1 for it in items if it.name != "all")
            summary = self._backends.data.domain_summary(mode, domain)
            right: str = summary or self.badge(mode, count)
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

    def _show_factory_plugins_menu(self) -> None:
        menu = self._push_menu("Factory Plugins", [], back=True)
        menu.set_progress("Factory Plugins", 0.0, "Checking download size...", done=False)
        self._mark_dirty(None)

        def _fetch() -> None:
            size = self._backends.data.factory_plugin_size()
            size_str = human_size(size) if size is not None else "unknown size"
            confirm = f"Reset all factory plugins?\n{size_str} download"

            def _do_reset() -> None:
                def _progress(status: str, frac: float, detail: str, done: bool) -> None:
                    menu.set_progress(status, frac, detail, done=done)
                    self._mark_dirty(None)

                self._backends.data.reset_factory_plugins(_progress)

            menu.set_rows(
                [Row((Target("Reset all factory plugins", _do_reset, confirm=confirm),))]
            )
            menu.clear_progress()
            self._mark_dirty(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _show_updates_menu(self) -> None:
        """Push the updates list directly, skipping the domain picker."""
        menu = self._push_menu(
            _MODE_TITLES[MODE_UPDATES],
            [],
            back=True,
            mode=MODE_UPDATES,
            domain=DOMAIN_SYSTEM,
            reload_callback=lambda: self._refresh_domain(MODE_UPDATES, DOMAIN_SYSTEM),
        )
        menu.set_progress(_MODE_TITLES[MODE_UPDATES], 0.0, "Wait a few seconds...", done=False)
        self._mark_dirty(None)

        def _run() -> None:
            self._backends.data.refresh_package_db()
            items = self._backends.data.domain_items(MODE_UPDATES, DOMAIN_SYSTEM)
            rows = self._build_domain_rows(items, MODE_UPDATES, DOMAIN_SYSTEM)
            menu.set_rows(rows)
            menu.clear_progress()
            self._mark_dirty(None)

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def badge(mode: str, count: int) -> str:
        if count == 0:
            return ""
        return f"{count} available"

    def _build_domain_rows(self, items: list[Item], mode: str, domain: str) -> list[Row]:
        """Build the row list for a domain screen, handling 'all' and special items."""
        if not items:
            empty = "No updates available" if mode == MODE_UPDATES else "Nothing to reset"
            return [Row((Target(empty, lambda: None, enabled=False),))]
        pkg_names = [it.name for it in items if it.name != "all"]
        rows: list[Row] = []
        for it in items:
            if it.name == "all":
                target = Target(
                    it.label,
                    lambda names=pkg_names: self._install_packages(names),
                    confirm=f"Update all {len(pkg_names)} packages?",
                )
            elif it.name.startswith("_"):
                # Informational/error items (e.g. "_offline" for no internet)
                target = Target(it.label, lambda: None, enabled=False)
            else:
                target = self._item_target(it, mode, domain)
            rows.append(Row((target,), right=it.right))
        return rows

    def _show_domain(self, mode: str, domain: str) -> None:
        items: list[Item] = self._backends.data.domain_items(mode, domain)
        domain_label: str = self._domain_label(domain)
        rows = self._build_domain_rows(items, mode, domain)
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
            if item.actions:
                action = item.actions[0]
                return Target(
                    item.label,
                    self._wrap_with_refresh(action.callback, mode, domain),
                    confirm=action.confirm,
                )
            return Target(
                item.label,
                lambda it=item: self._show_package_detail(it, mode, domain),
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

    def _show_package_detail(self, item: Item, mode: str, domain: str) -> None:
        """Push a detail screen showing description/changelog then an Install button."""
        name = item.name
        old_ver = item.label.removeprefix(name).strip()
        new_ver = item.right.lstrip("↑")

        install_target = Target(
            "Install",
            lambda: self._install_packages([name]),
        )

        def reload_cb() -> None:
            self.pop_screen()
            self._refresh_domain(mode, domain)

        menu = self._push_menu(
            name,
            [],
            back=True,
            mode=mode,
            domain=domain,
            reload_callback=reload_cb,
        )
        menu.set_progress(name, 0.0, "Loading...", done=False)
        self._mark_dirty(None)

        def _run() -> None:
            detail = self._backends.data.package_detail(name)
            rows: list[Row] = [
                Row(prefix=f"{old_ver} → {new_ver}"),
                Row(prefix="---", separator=True),
            ]
            for line in detail:
                for wrapped in textwrap.wrap(line, 38) or [""]:
                    rows.append(Row(prefix=wrapped))
            rows.append(Row(prefix="---", separator=True))
            rows.append(Row((install_target,)))
            menu.set_rows(rows)
            menu.clear_progress()
            self._mark_dirty(None)

        threading.Thread(target=_run, daemon=True).start()

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
        rows = self._build_domain_rows(items, mode, domain)
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
        for domain, label in self._backends.data.domains(mode):
            items = self._backends.data.domain_items(mode, domain)
            count: int = sum(1 for it in items if it.name != "all")
            summary: str = self._backends.data.domain_summary(mode, domain)
            right: str = summary or self.badge(mode, count)
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
                self._mark_dirty(None)

        self._backends.data.install_packages(packages, progress)

    # -- service restarts ---------------------------------------------------

    def _restart_service(
        self,
        label: str,
        service_names: list[str],
        restart_fn: Callable[[], bool],
    ) -> None:
        menu = self.current_screen()
        if not isinstance(menu, MenuScreen):
            return
        menu.set_progress(f"Restarting {label}...", 0.0, f"Restarting {label}...", False)
        self._mark_dirty(None)

        def _run() -> None:
            restart_fn()
            info: CrashInfo = self._backends.services.diagnose_services(service_names)
            if info.failed_service:
                self._push_restart_result(label, service_names, restart_fn, info)
            else:
                menu.set_progress(
                    f"{label} running",
                    1.0,
                    f"{label} restarted OK. Click to continue.",
                    done=True,
                )
            self._mark_dirty(None)

        threading.Thread(target=_run, daemon=True).start()

    def _push_restart_result(
        self,
        label: str,
        service_names: list[str],
        restart_fn: Callable[[], bool],
        info: CrashInfo,
    ) -> None:
        rows: list[Row] = []
        for svc, state in info.service_states.items():
            marker: str = "  <--" if state == "failed" else ""
            rows.append(Row(prefix=f"{svc}: {state}{marker}"[:_RESTART_MAX_COLS]))
        if info.crash_log:
            rows.append(Row(prefix=""))
            for line in info.crash_log.split("\n")[-5:]:
                rows.append(Row(prefix=line[:_RESTART_MAX_COLS]))
        rows.append(Row(prefix=""))

        def _retry() -> None:
            self.pop_screen()
            self._restart_service(label, service_names, restart_fn)

        rows.append(Row((Target("BACK", self.pop_screen), Target("RETRY", _retry))))
        self._push_menu(f"Restart {label} Failed", rows, back=True)

    # -- exit ---------------------------------------------------------------

    def _resume_main_app(self) -> None:
        logger.info("Resuming main app")
        self._backends.services.start_main_app()
        self._running = False
