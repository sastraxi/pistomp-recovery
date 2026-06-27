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
        self._update_items: list[Item] | None = None

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

    def _fetch_update_items(self) -> list[Item]:
        """Run check_updates() and return the resulting Item list (no cache read/write)."""
        out: list[Item] = []
        for facet in self._facets_for("system"):
            try:
                out += facet.remote_updates()
            except Exception:
                logger.debug("Could not query system updates", exc_info=True)
        return out

    def refresh_package_db(self) -> None:
        if not self.has_internet():
            return
        self._manager.sync_db()
        # Pre-fetch and cache so domain_items() is instant after the sync.
        self._update_items = self._fetch_update_items()

    def package_detail(self, name: str) -> list[str]:
        return self._manager.package_detail(name)

    def _remove_from_update_cache(self, packages: list[str]) -> None:
        """Drop installed packages from the cached update list."""
        if self._update_items is None:
            return
        pkg_set = set(packages)
        remaining = [it for it in self._update_items if it.name not in pkg_set and it.name != "all"]
        if len(remaining) > 1:
            remaining.append(Item(
                name="all",
                label="Update All",
                dirty=False,
                right=f"{len(remaining)} pkgs",
                actions=[],
            ))
        self._update_items = remaining

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
        if mode == "updates":
            if self._internet is False:
                has_packages = "packages" in DOMAIN_FACETS.get(domain, ())
                if has_packages:
                    return [Item("_offline", "No internet", False, "", [])]
            if domain == "system":
                if self._update_items is not None:
                    return self._update_items
                result = self._fetch_update_items()
                self._update_items = result
                return result
            return []
        out: list[Item] = []
        for facet in self._facets_for(domain):
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

    def _pkg_label(self, packages: list[str]) -> str:
        """Short description of the package(s) being installed, for status lines."""
        if len(packages) == 1:
            pkg = packages[0]
            new_ver = next(
                (it.right.lstrip("↑") for it in (self._update_items or []) if it.name == pkg),
                "",
            )
            return f"{pkg} → {new_ver}" if new_ver else pkg
        return f"{len(packages)} packages"

    def install_packages(
        self,
        packages: list[str],
        progress: ProgressCallback,
    ) -> bool:
        """Run download/install/stamp on a worker thread and report progress."""
        result: list[bool] = []

        def _run() -> None:
            label = self._pkg_label(packages)
            progress("Downloading", 0.0, label, False)
            if not self._manager.download(packages):
                progress("Download failed", 0.0, "Click to continue.", True)
                result.append(False)
                return

            progress("Installing", 0.5, label, False)
            if not self._manager.install(packages):
                progress("Rolling back", 0.5, "Install failed — restoring...", False)
                self._manager.install_from_cache(packages)
                progress("Install failed", 0.0, "Click to continue.", True)
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
                progress("Restarting", 0.95, svc, False)
                subprocess.run(["sudo", "systemctl", "restart", svc], check=False)

            if "pistomp-recovery" in packages:
                progress("Restarting", 1.0, "pistomp-recovery", False)
                subprocess.run(["sudo", "systemctl", "restart", "pistomp-recovery"], check=False)
                return

            self._remove_from_update_cache(packages)
            progress("Done", 1.0, "Click to continue.", True)
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
