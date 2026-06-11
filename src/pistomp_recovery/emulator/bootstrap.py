"""Bootstrap the emulator — creates a live recovery UI in a pygame window.

Usage:
    python -m pistomp_recovery.emulator
    python -m pistomp_recovery.emulator --force-crash

Keyboard shortcuts:
    ← / →       navigate menu
    Enter/Space  select
    L            long press (back/cancel)
    Esc          quit
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import time

import pygame

from pistomp_recovery.constants import LCD_HEIGHT, LCD_WIDTH
from pistomp_recovery.emulator.controls import FakeEncoderInput, FakeInputManager
from pistomp_recovery.emulator.lcd_pygame import LcdPygame
from pistomp_recovery.emulator.window import EmulatorWindow
from pistomp_recovery.items import Action, Item
from pistomp_recovery.service import BootMode, CrashInfo
from pistomp_recovery.ui.screens import Screen
from pistomp_recovery.ui.screens.crash import CrashScreen
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.screens.system_info import SystemInfoScreen
from pistomp_recovery.ui.widgets.confirm_dialog import ConfirmDialog
from pistomp_recovery.ui.widgets.misc import InputEvent

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 0.02

# ---------------------------------------------------------------------------
# Stub data that covers all four states:
#   Clean (stamped, unchanged)    ->  "✓ 2d ago"
#   Dirty (stamped, changed)      ->  "*" + "2d ago"
#   Factory (never modified)       ->  "factory"
#   Unknown (modified, no stamp)   ->  "*" + "?"
# ---------------------------------------------------------------------------

STUB_PEDALBOARDS: list[Item] = [
    Item(
        name="AmpBud.pedalboard",
        label="AmpBud.pedalboard",
        dirty=True,
        right="2d ago",
        actions=[
            Action("Rollback to stamp", lambda: None, "Rollback?"),
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
    Item(
        name="Beths.pedalboard",
        label="Beths.pedalboard",
        dirty=False,
        right="✓ 3d ago",
        actions=[
            Action("Rollback to stamp", lambda: None, "Rollback?"),
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
    Item(
        name="Carbon-Copy.pedalboard",
        label="Carbon-Copy.pedalboard",
        dirty=True,
        right="?",
        actions=[
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
    Item(
        name="factory-defaults.pedalboard",
        label="factory-defaults.pedalboard",
        dirty=False,
        right="factory",
        actions=[
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
]

STUB_PACKAGES: list[Item] = [
    Item(
        name="jack2-pistomp",
        label="jack2-pistomp",
        dirty=True,
        right="↑1.9.13",
        actions=[
            Action("Update to 1.9.13", lambda: None, "Update?"),
            Action("Rollback to stamp", lambda: None, "Rollback?"),
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
    Item(
        name="mod-ui",
        label="mod-ui",
        dirty=False,
        right="↑0.14.0",
        actions=[
            Action("Update to 0.14.0", lambda: None, "Update?"),
            Action("Rollback to stamp", lambda: None, "Rollback?"),
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
    Item(
        name="pi-stomp",
        label="pi-stomp",
        dirty=False,
        right="✓ 4d ago",
        actions=[
            Action("Rollback to stamp", lambda: None, "Rollback?"),
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
    Item(
        name="pistomp-recovery",
        label="pistomp-recovery",
        dirty=True,
        right="?",
        actions=[
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
]

STUB_CONFIG: list[Item] = [
    Item(
        name="config",
        label="Config",
        dirty=True,
        right="2d ago",
        actions=[
            Action("Rollback to stamp", lambda: None, "Rollback?"),
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
]

STUB_SYSTEM: list[Item] = [
    Item(
        name="system",
        label="System",
        dirty=False,
        right="factory",
        actions=[
            Action("Rollback to factory", lambda: None, "Factory reset?"),
        ],
    ),
]

STUB_UPDATES: list[tuple[str, str, str]] = [
    ("jack2-pistomp", "1.9.12", "1.9.13"),
    ("mod-ui", "0.13.0", "0.14.0"),
]


def _stub_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Safe systemctl stub for macOS / non-systemd environments."""
    return subprocess.CompletedProcess(
        args=list(args),
        returncode=0,
        stdout="active\n",
        stderr="",
    )


class EmulatorApp:
    def __init__(self, boot_mode: BootMode = BootMode.USER_RECOVERY) -> None:
        self._boot_mode: BootMode = boot_mode
        self._running: bool = True
        self._lcd: LcdPygame = LcdPygame()
        self._encoder: FakeEncoderInput = FakeEncoderInput()
        self._input: FakeInputManager = FakeInputManager(self._encoder)
        self._surface: pygame.Surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
        self._window: EmulatorWindow | None = None
        self._screen_stack: list[Screen] = []
        self._confirm_active: bool = False
        self._confirm_dialog: ConfirmDialog | None = None
        self._dirty: bool = True

    def init(self) -> None:
        pygame.init()
        self._lcd.init()
        self._window = EmulatorWindow(
            lcd_surface=self._surface,
            send_event=self._inject_event,
        )
        logger.info("Emulator initialized (boot mode: %s)", self._boot_mode.name)

        if self._boot_mode == BootMode.CRASH_RECOVERY:
            crash_info: CrashInfo = CrashInfo(
                boot_mode=BootMode.CRASH_RECOVERY,
                failed_service="mod-host",
                crash_log=(
                    "Traceback (most recent call last):\n"
                    "  File 'modalapistomp.py', line 42\n"
                    "    handler.poll_controls()\n"
                    "AttributeError: 'NoneType' object"
                    " has no attribute 'poll_controls'"
                ),
                service_states={
                    "jack": "active",
                    "mod-host": "failed",
                    "mod-ui": "inactive",
                    "mod-ala-pi-stomp": "inactive",
                },
            )
            screen: CrashScreen = CrashScreen(
                self._surface,
                crash_info=crash_info,
                on_resume=self._resume,
                on_recovery=self._show_main_menu,
            )
            self._push_screen(screen)
        else:
            self._show_main_menu()

    def _inject_event(self, event: InputEvent) -> None:
        self._input.inject_event(event)

    def _push_screen(self, screen: Screen) -> None:
        screen.set_back_callback(self._pop_screen)
        self._screen_stack.append(screen)
        self._dirty = True

    def _pop_screen(self) -> None:
        if len(self._screen_stack) > 1:
            self._screen_stack.pop()
            self._dirty = True

    def _show_main_menu(self) -> None:
        dirty: int = sum(1 for p in STUB_PEDALBOARDS if p.dirty)
        dirty += sum(1 for p in STUB_PACKAGES if p.dirty)
        dirty += sum(1 for p in STUB_CONFIG if p.dirty)
        dirty += sum(1 for p in STUB_SYSTEM if p.dirty)
        updates: int = sum(1 for p in STUB_PACKAGES if p.right.startswith("↑"))

        items: list[Item] = [
            Item("resume", "Resume", False, "",
                 [Action("Resume", self._resume)]),
        ]
        if dirty > 0:
            items.append(
                Item("reset", "Reset...", True,
                     f"{dirty} changed",
                     [Action("Open", self._show_reset)]),
            )
        if updates > 0:
            items.append(
                Item("update", "Update...", False,
                     f"{updates} available",
                     [Action("Open", self._show_updates)]),
            )
        items.extend([
            Item("pedalboards", "Pedalboards...", False, "",
                 [Action("Open", self._show_pedalboards)]),
            Item("packages", "Packages...", False, "",
                 [Action("Open", self._show_packages)]),
            Item("config", "Config...", False, "",
                 [Action("Open", self._show_config)]),
            Item("system", "System...", False, "",
                 [Action("Open", self._show_system)]),
            Item("system_info", "System Info...", False, "",
                 [Action("Open", self._show_system_info)]),
            Item("reboot", "Reboot", False, "",
                 [Action("Reboot",
                  lambda: logger.info("Reboot (emulated)"))]),
            Item("power_off", "Power Off", False, "",
                 [Action("Power Off",
                  lambda: setattr(self, "_running", False))]),
        ])

        menu: MenuScreen = MenuScreen(
            self._surface,
            title="Recovery",
            items=items,
            back_callback=None,
        )
        self._push_screen(menu)

    def _show_reset(self) -> None:
        dirty_items: list[Item] = (
            [p for p in STUB_PEDALBOARDS if p.dirty]
            + [p for p in STUB_PACKAGES if p.dirty]
            + [p for p in STUB_CONFIG if p.dirty]
            + [p for p in STUB_SYSTEM if p.dirty]
        )
        screen: MenuScreen = MenuScreen(
            self._surface,
            title="Reset",
            items=dirty_items,
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_updates(self) -> None:
        update_items: list[Item] = []
        for pkg, old_ver, new_ver in STUB_UPDATES:
            update_items.append(
                Item(
                    name=pkg,
                    label=f"{pkg} {old_ver} → {new_ver}",
                    dirty=False,
                    right="",
                    actions=[
                        Action(
                            f"Update to {new_ver}",
                            lambda p=pkg: logger.info(
                                "Install %s (emulated)", p),
                            confirm=f"Update {pkg}?",
                        ),
                    ],
                )
            )
        update_items.append(
            Item(
                name="all",
                label="Update All",
                dirty=False,
                right="",
                actions=[
                    Action(
                        "Update All",
                        lambda: logger.info("Install all (emulated)"),
                        confirm="Update all?",
                    )
                ],
            )
        )
        screen: MenuScreen = MenuScreen(
            self._surface,
            title="Updates",
            items=update_items,
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_pedalboards(self) -> None:
        screen: MenuScreen = MenuScreen(
            self._surface,
            title="Pedalboards",
            items=list(STUB_PEDALBOARDS),
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_packages(self) -> None:
        screen: MenuScreen = MenuScreen(
            self._surface,
            title="Packages",
            items=list(STUB_PACKAGES),
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_config(self) -> None:
        screen: MenuScreen = MenuScreen(
            self._surface,
            title="Config",
            items=list(STUB_CONFIG),
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_system(self) -> None:
        screen: MenuScreen = MenuScreen(
            self._surface,
            title="System",
            items=list(STUB_SYSTEM),
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_system_info(self) -> None:
        # Stub systemctl so get_system_info doesn't crash on macOS
        import pistomp_recovery.service as svc
        original_run = subprocess.run
        svc._original_run = original_run  # type: ignore[attr-defined]

        def safe_run(
            cmd: "str | list[str]", **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if isinstance(cmd, list) and cmd[0] == "systemctl":
                return _stub_systemctl(*cmd)
            return original_run(cmd, **kwargs)  # type: ignore[arg-type]

        subprocess.run = safe_run  # type: ignore[assignment]
        try:
            screen: SystemInfoScreen = SystemInfoScreen(self._surface)
            screen.refresh()
            self._push_screen(screen)
        finally:
            subprocess.run = original_run  # type: ignore[assignment]

    def _resume(self) -> None:
        logger.info("Resume pressed (emulated)")

    def run(self) -> None:
        assert self._window is not None
        while self._running:
            if not self._window.process_events():
                break

            events: list[InputEvent] = self._input.poll()
            for event in events:
                self._handle_event(event)

            if self._dirty:
                self._draw_current_screen()
                self._window.render()
                self._dirty = False
            time.sleep(POLL_INTERVAL)

    def _handle_event(self, event: InputEvent) -> None:
        screen: Screen | None = self._screen_stack[-1] if self._screen_stack else None
        if screen is None:
            return

        if self._confirm_active and self._confirm_dialog is not None:
            self._confirm_dialog.handle_event(event)
            return

        if not screen.handle_event(event):
            if event == InputEvent.LONG_CLICK:
                self._pop_screen()
        else:
            self._dirty = True

    def _draw_current_screen(self) -> None:
        screen: Screen | None = self._screen_stack[-1] if self._screen_stack else None
        if screen is None:
            return
        screen.draw()


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="pistomp-recovery emulator"
    )
    parser.add_argument("--log", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--force-crash", action="store_true",
                        help="Start in crash recovery mode")
    args: argparse.Namespace = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log),
        format="%(levelname)s:%(name)s:%(message)s",
    )

    boot_mode: BootMode = (
        BootMode.CRASH_RECOVERY if args.force_crash else BootMode.USER_RECOVERY
    )
    app: EmulatorApp = EmulatorApp(boot_mode)

    try:
        app.init()
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
