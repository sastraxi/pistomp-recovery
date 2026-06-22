"""Backends that talk to the real pi-Stomp device.

These wrap SPI/GPIO, pacman, git, and systemd.  The recovery UI core is
oblivious to the implementation; it just receives `Item` lists and calls
progress callbacks.
"""

from __future__ import annotations

import logging
import threading

import pygame

from pistomp_recovery.backends import (
    AppBackends,
    DataBackend,
    DisplayBackend,
    InputBackend,
    ProgressCallback,
    ServiceBackend,
)
from pistomp_recovery.facet import all_facets, register_default_facets
from pistomp_recovery.hardware.encoder import EncoderInput
from pistomp_recovery.hardware.lcd import LcdSpi
from pistomp_recovery.hardware.switch import AdcSwitch
from pistomp_recovery.items import Item
from pistomp_recovery.packages.manager import PackageManager, detect_package_manager
from pistomp_recovery.packages.packages import stamp_packages
from pistomp_recovery.service import (
    CrashInfo,
    diagnose_crash,
    diagnose_services,
    recovery_sha,
    restart_jack,
    restart_mod,
    start_main_app,
    stop_main_app,
)
from pistomp_recovery.ui.display import Display
from pistomp_recovery.ui.input import InputManager
from pistomp_recovery.ui.widgets.misc import InputEvent

logger = logging.getLogger(__name__)


class LcdDisplayBackend(DisplayBackend):
    """SPI LCD via pygame surface bridge."""

    def __init__(self) -> None:
        self._display: Display = Display(LcdSpi())

    @property
    def surface(self) -> pygame.Surface:
        return self._display.surface

    def init(self) -> None:
        self._display.init()

    def update(self, surface: pygame.Surface) -> None:
        self._display.update(surface)


class GpioInputBackend(InputBackend):
    """Rotary encoder + switch on real GPIO/ADC."""

    def __init__(self) -> None:
        self._encoder: EncoderInput = EncoderInput()
        self._switch: AdcSwitch = AdcSwitch()
        self._input: InputManager = InputManager(self._encoder, self._switch)

    def start(self) -> None:
        # InputManager owns starting/stopping the encoder and switch; calling
        # them here too would double-claim the GPIO pins (GPIOPinInUse).
        self._input.start()

    def stop(self) -> None:
        self._input.stop()

    def poll(self) -> list[InputEvent]:
        return self._input.poll()


class RealDataBackend(DataBackend):
    """Pedalboards, config, system files, and packages backed by git/package-manager."""

    def __init__(self, manager: PackageManager) -> None:
        self._manager = manager

    def domains(self) -> tuple[tuple[str, str], ...]:
        return (
            ("pedalboards", "Pedalboards"),
            ("plugins", "Plugins"),
            ("config", "Config"),
            ("system", "System"),
        )

    def domain_items(self, mode: str, domain: str) -> list[Item]:
        if domain == "plugins":
            return []
        if mode == "updates":
            # The core synthesizes update actions; backend just lists candidates.
            return self._update_items(domain)

        facet = all_facets().get(domain)
        if facet is None:
            return []
        try:
            raw: list[Item] = facet.list_items()
        except Exception:
            logger.debug("Could not list %s items", domain, exc_info=True)
            return []

        wanted: str = "Rollback to stamp" if mode == "checkpoint" else "Rollback to factory"
        result: list[Item] = []
        for it in raw:
            actions = [a for a in it.actions if a.label == wanted]
            if not actions:
                continue
            if mode == "checkpoint" and not it.dirty:
                continue
            result.append(Item(it.name, it.label, it.dirty, it.right, actions))
        return result

    def _update_items(self, domain: str) -> list[Item]:
        if domain == "plugins":
            return []
        facet = all_facets().get(domain)
        if facet is None:
            return []
        try:
            return facet.remote_updates()
        except Exception:
            logger.debug("Could not query %s updates", domain, exc_info=True)
            return []

    def install_packages(
        self,
        packages: list[str],
        progress: ProgressCallback,
    ) -> bool:
        """Run download/install/stamp on a worker thread and report progress."""
        result: list[bool] = []

        def _run() -> None:
            progress("Downloading...", 0.0, f"Downloading {len(packages)} package(s)...", False)
            if not self._manager.download(packages):
                progress("Download failed", 0.0, "Download failed. Click to continue.", True)
                result.append(False)
                return

            progress("Installing...", 0.5, f"Installing {len(packages)} package(s)...", False)
            if not self._manager.install(packages):
                progress("Rolling back...", 0.5, "Install failed, rolling back...", False)
                self._manager.install_from_cache(packages)
                progress("Install failed", 0.0, "Install failed. Click to continue.", True)
                result.append(False)
                return

            progress("Saving snapshot...", 0.9, "Saving snapshot...", False)
            try:
                stamp_packages()
            except Exception:
                logger.exception("Stamp after update failed")

            progress("Update complete", 1.0, "Done. Exit (►) to restart pi-Stomp.", True)
            result.append(True)

        threading.Thread(target=_run, daemon=True).start()
        return True


class RealServiceBackend(ServiceBackend):
    """systemd lifecycle and crash diagnostics."""

    def stop_main_app(self) -> bool:
        return stop_main_app()

    def start_main_app(self) -> bool:
        return start_main_app()

    def restart_jack(self) -> bool:
        return restart_jack()

    def restart_mod(self) -> bool:
        return restart_mod()

    def diagnose_services(self, services: list[str]) -> CrashInfo:
        return diagnose_services(services)

    def reboot(self) -> None:
        import subprocess

        subprocess.run(["sudo", "systemctl", "reboot"], check=False)

    def power_off(self) -> None:
        import subprocess

        subprocess.run(["sudo", "systemctl", "poweroff"], check=False)

    def recovery_sha(self) -> str:
        return recovery_sha()

    def crash_info(self) -> CrashInfo | None:
        return diagnose_crash()


def make_real_backends() -> AppBackends:
    manager = detect_package_manager()
    register_default_facets(manager)
    return AppBackends(
        display=LcdDisplayBackend(),
        input=GpioInputBackend(),
        data=RealDataBackend(manager),
        services=RealServiceBackend(),
    )
