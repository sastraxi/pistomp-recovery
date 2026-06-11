from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import time

from pistomp_recovery.config import list_config_items
from pistomp_recovery.hardware.encoder import EncoderInput
from pistomp_recovery.items import Action, Item
from pistomp_recovery.packages import get_available_updates, list_package_items
from pistomp_recovery.packages.installer import (
    download_packages,
    install_from_cache,
    install_packages,
)
from pistomp_recovery.pedalboards import list_pedalboard_items, rollback_pedalboard
from pistomp_recovery.service import (
    BootMode,
    CrashInfo,
    diagnose_crash,
    get_boot_mode,
    start_main_app,
    stop_main_app,
)
from pistomp_recovery.system import list_system_items
from pistomp_recovery.ui.display import Display
from pistomp_recovery.ui.input import InputManager
from pistomp_recovery.ui.screens import Screen
from pistomp_recovery.ui.screens.crash import CrashScreen
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.screens.system_info import SystemInfoScreen
from pistomp_recovery.ui.widgets.confirm_dialog import ConfirmDialog
from pistomp_recovery.ui.widgets.misc import InputEvent

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 0.03


def _reboot() -> None:
    subprocess.run(["systemctl", "reboot"], check=False)


def _power_off() -> None:
    subprocess.run(["systemctl", "poweroff"], check=False)


class RecoveryApp:
    def __init__(self, boot_mode: BootMode) -> None:
        self._boot_mode: BootMode = boot_mode
        self._running: bool = True
        self._dirty: bool = True
        self._display: Display = Display()
        self._encoder: EncoderInput = EncoderInput()
        self._input: InputManager = InputManager(self._encoder)
        self._screen_stack: list[Screen] = []
        self._confirm_active: bool = False
        self._confirm_dialog: ConfirmDialog | None = None

    def init(self) -> None:
        stop_main_app()
        self._display.init()
        self._encoder.start()
        self._input.start()
        logger.info("Recovery app initialized (boot mode: %s)", self._boot_mode.name)

        if self._boot_mode == BootMode.CRASH_RECOVERY:
            crash_info: CrashInfo = diagnose_crash()
            screen: CrashScreen = CrashScreen(
                self._display.surface,
                crash_info=crash_info,
                on_resume=self._resume_main_app,
                on_recovery=self._show_main_menu,
            )
            self._push_screen(screen)
        else:
            self._show_main_menu()

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        while self._running:
            events: list[InputEvent] = self._input.poll()
            for event in events:
                self._handle_event(event)
            if self._dirty:
                self._draw_current_screen()
                self._display.update(self._display.surface)
                self._dirty = False
            time.sleep(POLL_INTERVAL)

    def _push_screen(self, screen: Screen) -> None:
        screen.set_back_callback(self._pop_screen)
        self._screen_stack.append(screen)
        self._dirty = True

    def _pop_screen(self) -> None:
        if len(self._screen_stack) > 1:
            self._screen_stack.pop()
            self._dirty = True

    def _current_screen(self) -> Screen | None:
        return self._screen_stack[-1] if self._screen_stack else None

    def _handle_event(self, event: InputEvent) -> None:
        screen: Screen | None = self._current_screen()
        if screen is None:
            return

        if self._confirm_active and self._confirm_dialog is not None:
            consumed: bool = self._confirm_dialog.handle_event(event)
            if consumed:
                self._dirty = True
            return

        if not screen.handle_event(event):
            if event == InputEvent.LONG_CLICK:
                self._pop_screen()
        else:
            self._dirty = True

    def _draw_current_screen(self) -> None:
        screen: Screen | None = self._current_screen()
        if screen is None:
            return
        screen.draw()
        if self._confirm_active and self._confirm_dialog is not None:
            self._confirm_dialog.draw()

    def _show_main_menu(self) -> None:
        dirty_count: int = 0
        update_count: int = 0
        try:
            pb_items = list_pedalboard_items()
            dirty_count += sum(1 for i in pb_items if i.dirty)
            pkg_items = list_package_items()
            dirty_count += sum(1 for i in pkg_items if i.dirty)
            updates: list[tuple[str, str, str]] = get_available_updates()
            update_count = len(updates)
        except Exception:
            logger.debug("Could not query dirty/update counts", exc_info=True)

        items: list[Item] = [
            Item("resume", "Resume", False, "", [Action("Resume", self._resume_main_app)]),
        ]
        if dirty_count > 0:
            items.append(
                Item(
                    "reset",
                    "Reset...",
                    True,
                    f"{dirty_count} changed",
                    [Action("Open", self._show_reset)],
                )
            )
        if update_count > 0:
            items.append(
                Item(
                    "update",
                    "Update...",
                    False,
                    f"{update_count} available",
                    [Action("Open", self._show_updates)],
                )
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
            Item("reboot", "Reboot", False, "", [Action("Reboot", _reboot)]),
            Item("power_off", "Power Off", False, "",
                 [Action("Power Off", _power_off)]),
        ])

        menu: MenuScreen = MenuScreen(
            self._display.surface,
            title="Recovery",
            items=items,
            back_callback=None,
        )
        self._push_screen(menu)

    def _show_reset(self) -> None:
        items: list[Item] = []
        try:
            for pb in list_pedalboard_items():
                if pb.dirty:
                    items.append(
                        Item(
                            name=pb.name,
                            label=pb.label + (" *" if pb.dirty else ""),
                            dirty=pb.dirty,
                            right=pb.right,
                            actions=[
                                Action(
                                    "Rollback to stamp",
                                    lambda n=pb.name: rollback_pedalboard(n, "stamp"),
                                    confirm=f"Rollback {pb.name}\nto last stamp?",
                                ),
                                Action(
                                    "Rollback to factory",
                                    lambda n=pb.name: rollback_pedalboard(n, "factory"),
                                    confirm=f"Rollback {pb.name}\nto factory?",
                                ),
                            ],
                        )
                    )
            for pkg in list_package_items():
                if pkg.dirty:
                    actions: list[Action] = []
                    for a in pkg.actions:
                        if a.label == "Rollback to stamp":
                            actions.append(a)
                    for a in pkg.actions:
                        if a.label == "Rollback to factory":
                            actions.append(a)
                    items.append(
                        Item(
                            name=pkg.name,
                            label=pkg.label,
                            dirty=pkg.dirty,
                            right=pkg.right,
                            actions=actions,
                        )
                    )
        except Exception:
            logger.debug("Could not query dirty items", exc_info=True)

        screen: MenuScreen = MenuScreen(
            self._display.surface,
            title="Reset",
            items=items,
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_updates(self) -> None:
        updates: list[tuple[str, str, str]] = []
        try:
            updates = get_available_updates()
        except Exception:
            logger.debug("Could not query updates", exc_info=True)

        update_items: list[Item] = []
        for pkg, old_ver, new_ver in updates:
            update_items.append(
                Item(
                    name=pkg,
                    label=f"{pkg} {old_ver} \u2192 {new_ver}",
                    dirty=False,
                    right="",
                    actions=[
                        Action(
                            f"Update to {new_ver}",
                            lambda p=pkg: self._install_packages([p]),
                            confirm=f"Update {pkg}\nto {new_ver}?",
                        ),
                    ],
                )
            )
        if update_items:
            update_items.append(
                Item(
                    name="all",
                    label="Update All",
                    dirty=False,
                    right="",
                    actions=[
                        Action(
                            "Update All",
                            lambda: self._install_packages([p for p, _, _ in updates]),
                            confirm="Update all packages?",
                        ),
                    ],
                )
            )
        else:
            update_items.append(
                Item(
                    name="none",
                    label="No updates available",
                    dirty=False,
                    right="",
                    actions=[],
                )
            )

        self._updates_screen: MenuScreen = MenuScreen(
            self._display.surface,
            title="Updates",
            items=update_items,
            back_callback=self._pop_screen,
        )
        self._push_screen(self._updates_screen)

    def _show_pedalboards(self) -> None:
        items: list[Item] = []
        try:
            items = list_pedalboard_items()
        except Exception:
            logger.debug("Could not list pedalboards", exc_info=True)

        screen: MenuScreen = MenuScreen(
            self._display.surface,
            title="Pedalboards",
            items=items,
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_packages(self) -> None:
        items: list[Item] = []
        try:
            items = list_package_items()
        except Exception:
            logger.debug("Could not list packages", exc_info=True)

        screen: MenuScreen = MenuScreen(
            self._display.surface,
            title="Packages",
            items=items,
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_config(self) -> None:
        items: list[Item] = []
        try:
            items = list_config_items()
        except Exception:
            logger.debug("Could not list config", exc_info=True)

        screen: MenuScreen = MenuScreen(
            self._display.surface,
            title="Config",
            items=items,
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_system(self) -> None:
        items: list[Item] = []
        try:
            items = list_system_items()
        except Exception:
            logger.debug("Could not list system", exc_info=True)

        screen: MenuScreen = MenuScreen(
            self._display.surface,
            title="System",
            items=items,
            back_callback=self._pop_screen,
        )
        self._push_screen(screen)

    def _show_system_info(self) -> None:
        screen: SystemInfoScreen = SystemInfoScreen(self._display.surface)
        screen.refresh()
        self._push_screen(screen)

    def _confirm_factory_reset(self) -> None:
        self._confirm_active = True
        self._confirm_dialog = ConfirmDialog(
            self._display.surface,
            "Factory reset\nall data?",
            self._do_factory_reset,
            self._cancel_confirm,
        )
        self._dirty = True

    def _cancel_confirm(self) -> None:
        self._confirm_active = False
        self._confirm_dialog = None
        self._dirty = True

    def _do_factory_reset(self) -> None:
        self._confirm_active = False
        self._confirm_dialog = None
        self._dirty = True
        try:
            from pistomp_recovery.config import rollback_config
            from pistomp_recovery.packages import rollback_package
            from pistomp_recovery.pedalboards import rollback_pedalboard
            from pistomp_recovery.system import rollback_system

            for pb in list_pedalboard_items():
                rollback_pedalboard(pb.name, "factory")
            for pkg in list_package_items():
                rollback_package(pkg.name, "factory")
            rollback_config("factory")
            rollback_system("factory")
        except Exception:
            logger.exception("Factory reset failed")
        subprocess.run(["systemctl", "reboot"], check=False)

    def _install_packages(self, packages: list[str]) -> None:
        screen: MenuScreen | None = None
        current: Screen | None = self._current_screen()
        if isinstance(current, MenuScreen):
            screen = current

        if screen is not None:
            screen.set_progress("Downloading...", 0.0, f"Downloading {len(packages)} packages...")
            self._dirty = True
        if not download_packages(packages):
            if screen is not None:
                screen.set_progress("Download failed", 0.0, "Download failed")
                self._dirty = True
            return

        if screen is not None:
            screen.set_progress("Installing...", 0.5, f"Installing {len(packages)} packages...")
            self._dirty = True
        if not install_packages(packages):
            if screen is not None:
                screen.set_progress("Rolling back...", 0.5, "Install failed, rolling back...")
                self._dirty = True
            install_from_cache(packages)
            if screen is not None:
                screen.set_progress("Install failed", 0.0, "Install failed")
                self._dirty = True
            return

        if screen is not None:
            screen.set_progress("Saving snapshot...", 0.9, "Saving snapshot...")
            self._dirty = True
        try:
            from pistomp_recovery.packages import stamp_packages
            stamp_packages()
        except Exception:
            logger.exception("Stamp after update failed")

        if screen is not None:
            screen.set_progress(
                "Update complete", 1.0,
                "Update complete. Press Resume to restart.")
            self._dirty = True

    def _resume_main_app(self) -> None:
        logger.info("Resuming main app")
        start_main_app()
        self._running = False

    def cleanup(self) -> None:
        self._encoder.stop()
        self._input.stop()
        logger.info("Recovery app cleaned up")


def main(args: list[str] | None = None) -> None:
    desc = "pi-Stomp Recovery Service"
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=desc)
    parser.add_argument("--log", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--force-crash", action="store_true", help="Force crash recovery mode")
    parser.add_argument("--force-menu", action="store_true", help="Force recovery menu mode")
    parsed: argparse.Namespace = parser.parse_args(args)

    logging.basicConfig(
        level=getattr(logging, parsed.log),
        format="%(levelname)s:%(name)s:%(message)s",
    )

    if parsed.force_crash:
        boot_mode: BootMode = BootMode.CRASH_RECOVERY
    elif parsed.force_menu:
        boot_mode = BootMode.USER_RECOVERY
    else:
        boot_mode = get_boot_mode()

    app: RecoveryApp = RecoveryApp(boot_mode)

    def handle_signal(signum: int, frame: object) -> None:
        logger.info("Received signal %d, shutting down", signum)
        app.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        app.init()
        app.run()
    except Exception:
        logger.exception("Recovery app crashed")
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()
