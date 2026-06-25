"""Backends that talk to the real pi-Stomp device.

These wrap SPI/GPIO, pacman, git, and systemd.  The recovery UI core is
oblivious to the implementation; it just receives `Item` lists and calls
progress callbacks.
"""

from __future__ import annotations

import logging
import socket
import subprocess
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
from pistomp_recovery.constants import DOMAIN_FACETS, services_for_packages
from pistomp_recovery.facet import Facet, all_facets, register_default_facets
from pistomp_recovery.hardware.encoder import EncoderInput
from pistomp_recovery.hardware.lcd import LcdSpi
from pistomp_recovery.hardware.switch import AdcSwitch
from pistomp_recovery.items import Item
from pistomp_recovery.packages.manager import PackageManager, detect_package_manager
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
from pistomp_recovery.ui.widgets.misc import Box, InputEvent

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

    def update(self, surface: pygame.Surface, rects: list[Box] | None = None) -> None:
        self._display.update(surface, rects)

    def transfer_ms(self, rect: Box | None = None) -> float:
        return self._display.transfer_ms(rect)


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
        self._internet: bool | None = None

    def has_internet(self) -> bool:
        if self._internet is None:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect(("8.8.8.8", 53))
                sock.close()
                self._internet = True
            except OSError:
                self._internet = False
        return self._internet

    def refresh_package_db(self) -> None:
        if not self.has_internet():
            return
        self._manager.sync_db()

    def domains(self, mode: str = "") -> tuple[tuple[str, str], ...]:
        all_domains: tuple[tuple[str, str], ...] = (
            ("pedalboards", "Pedalboards"),
            ("plugins", "Plugins"),
            ("config", "Config"),
            ("system", "System"),
        )
        if mode == "updates":
            # Only system (packages) has installable updates.
            return (("system", "System"),)
        return all_domains

    def _facets_for(self, domain: str) -> list[Facet]:
        facets = all_facets()
        return [f for key in DOMAIN_FACETS.get(domain, ()) if (f := facets.get(key)) is not None]

    def domain_items(self, mode: str, domain: str) -> list[Item]:
        if mode == "updates" and self._internet is False:
            has_packages = "packages" in DOMAIN_FACETS.get(domain, ())
            if has_packages:
                return [Item("_offline", "No internet", False, "", [])]
        out: list[Item] = []
        for facet in self._facets_for(domain):
            if mode == "updates":
                try:
                    out += facet.remote_updates()
                except Exception:
                    logger.debug("Could not query %s updates", facet.name, exc_info=True)
            else:
                try:
                    raw: list[Item] = facet.list_items()
                except Exception:
                    logger.debug("Could not list %s items", facet.name, exc_info=True)
                    continue
                wanted: str = (
                    "Rollback to stamp" if mode == "checkpoint" else "Rollback to factory"
                )
                for it in raw:
                    actions = [a for a in it.actions if a.label == wanted]
                    if not actions:
                        # Keep clean no-action items (e.g. missing plugin bundles)
                        # as informational rows in checkpoint mode.
                        if mode == "checkpoint" and not it.dirty:
                            out.append(Item(it.name, it.label, it.dirty, it.right, actions))
                        continue
                    if mode == "checkpoint" and not it.dirty:
                        continue
                    out.append(Item(it.name, it.label, it.dirty, it.right, actions))
        return out

    def domain_summary(self, mode: str, domain: str) -> str:
        if domain != "plugins" or mode != "factory":
            return ""
        facet = all_facets().get("plugins")
        cache_summary = getattr(facet, "cache_summary", None)
        if facet is None or cache_summary is None:
            return ""
        try:
            return cache_summary()
        except Exception:
            logger.debug("Could not compute plugins cache summary", exc_info=True)
            return ""

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

            to_restart = [
                svc
                for svc in services_for_packages(packages)
                if svc != "pistomp-recovery"
                and subprocess.run(
                    ["systemctl", "is-active", "--quiet", svc], check=False
                ).returncode
                == 0
            ]
            for svc in to_restart:
                progress(f"Restarting {svc}...", 0.95, f"Restarting {svc}...", False)
                subprocess.run(["sudo", "systemctl", "restart", svc], check=False)

            if "pistomp-recovery" in packages:
                progress("Restarting recovery...", 1.0, "Restarting recovery...", False)
                subprocess.run(["sudo", "systemctl", "restart", "pistomp-recovery"], check=False)
                return

            progress("Update complete", 1.0, "Done. Click to continue.", True)
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
