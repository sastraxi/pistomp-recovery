"""Emulator backends for the recovery UI.

These mirror the real device backends but use a pygame window, fake input,
and real recovery facets operating against temporary data. Each
`EmulatorDataBackend` instance owns its own temp directories so multiple
emulator instances do not share global mutable data.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pygame

from pistomp_recovery.backends import (
    AppBackends,
    DataBackend,
    DisplayBackend,
    InputBackend,
    ProgressCallback,
    ServiceBackend,
)
from pistomp_recovery.constants import (
    DOMAIN_FACETS,
    LCD_HEIGHT,
    LCD_WIDTH,
    PISTOMP_PACKAGES,
)
from pistomp_recovery.emulator.controls import FakeEncoderInput, FakeInputManager
from pistomp_recovery.facet import Facet, RollbackTarget, clear_facets, register_facet
from pistomp_recovery.file_facet import FileFacet
from pistomp_recovery.items import Action, Item, PackageUpdate
from pistomp_recovery.pedalboards import PedalboardFacet
from pistomp_recovery.service import BootMode, CrashInfo
from pistomp_recovery.ui.widgets.misc import Box, InputEvent
from pistomp_recovery.util import human_time

logger = logging.getLogger(__name__)


class PygameDisplayBackend(DisplayBackend):
    """Pygame window surface for macOS/Linux development."""

    def __init__(self) -> None:
        self._surface: pygame.Surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))

    @property
    def surface(self) -> pygame.Surface:
        return self._surface

    def init(self) -> None:
        self._surface.fill((0, 0, 0))

    def update(self, surface: pygame.Surface, rects: list[Box] | None = None) -> None:
        if surface is not self._surface:
            self._surface.blit(surface, (0, 0))

    def transfer_ms(self, rect: Box | None = None) -> float:
        # Emulator has no SPI; report a small constant so small clips go inline.
        return 0.0


class FakeInputBackend(InputBackend):
    """Keyboard-driven fake encoder + switch input."""

    def __init__(self, encoder: FakeEncoderInput) -> None:
        self._encoder: FakeEncoderInput = encoder
        self._input: FakeInputManager = FakeInputManager(self._encoder)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def poll(self) -> list[InputEvent]:
        return self._input.poll()

    def inject_event(self, event: InputEvent) -> None:
        self._input.inject_event(event)


class EmulatorPackageFacet:
    """Package facet that simulates pacman with in-memory state."""

    name = "packages"

    def __init__(self) -> None:
        self._installed: dict[str, str] = {pkg: "1.0.0" for pkg in PISTOMP_PACKAGES}
        self._stamped: dict[str, str] = dict(self._installed)
        self._factory: dict[str, str] = dict(self._installed)
        self._updates: list[PackageUpdate] = [
            PackageUpdate("jack2-pistomp", "1.0.0", "1.9.13"),
            PackageUpdate("mod-ui", "1.0.0", "0.14.0"),
        ]

    def init(self) -> None:
        pass

    def _collect_versions(self) -> dict[str, str]:
        return dict(self._installed)

    def _read_stamp_file(self) -> dict[str, str]:
        return dict(self._stamped)

    def pending_updates(self) -> list[PackageUpdate]:
        """Return the current list of pending package updates."""
        return list(self._updates)

    def list_items(self) -> list[Item]:
        self.init()
        installed: dict[str, str] = self._collect_versions()
        stamped: dict[str, str] = self._read_stamp_file()
        items: list[Item] = []
        for pkg in sorted(installed):
            is_dirty: bool = installed.get(pkg) != stamped.get(pkg)
            right: str = human_time(datetime.now(tz=timezone.utc)) if pkg in stamped else "factory"
            items.append(
                Item(
                    name=pkg,
                    label=f"{pkg} {installed[pkg]}" + (" *" if is_dirty else ""),
                    dirty=is_dirty,
                    right=right,
                    actions=[
                        Action(
                            "Rollback to stamp",
                            lambda n=pkg: self.rollback(n, "stamp"),
                            confirm=f"Rollback {pkg}\nto last stamp?",
                        ),
                        Action(
                            "Rollback to factory",
                            lambda n=pkg: self.rollback(n, "factory"),
                            confirm=f"Rollback {pkg}\nto factory?",
                        ),
                    ],
                )
            )
        return items

    def stamp(self) -> str | None:
        self._stamped = dict(self._installed)
        return None

    def rollback(self, name: str, target: RollbackTarget) -> None:
        version: str | None = None
        if target == "stamp":
            version = self._stamped.get(name)
        elif target == "factory":
            version = self._factory.get(name)
        if not version or version == "not-installed":
            logger.warning("No version found for %s in target %s", name, target)
            return
        logger.info("Rolling back %s to %s (emulated)", name, version)
        self._installed[name] = version

    def remove_updates(self, packages: list[str]) -> None:
        """Remove the given packages from the pending-update list."""
        self._updates = [u for u in self._updates if u.name not in packages]

    def remote_updates(self) -> list[Item]:
        items = [
            Item(
                u.name,
                f"{u.name} {u.old_version}",
                False,
                f"\u2191{u.new_version}",
                [],
            )
            for u in self._updates
        ]
        if len(items) > 1:
            items.append(Item(
                name="all",
                label="Update All",
                dirty=False,
                right=f"{len(items)} pkgs",
                actions=[],
            ))
        return items

    def install(self, pkg: str, new_version: str) -> None:
        """Simulate installing a package."""
        logger.info("Installing %s -> %s (emulated)", pkg, new_version)
        self._installed[pkg] = new_version
        self._updates = [u for u in self._updates if u.name != pkg]
        self.stamp()


class EmulatorDataBackend(DataBackend):
    """Data backend using real recovery facets (FileFacet, PedalboardFacet) on temp dirs."""

    def __init__(self) -> None:
        self._root: Path = Path(tempfile.mkdtemp(prefix="pistomp-recovery-emulator-"))
        self._config_dir: Path = self._root / "config"
        self._system_dir: Path = self._root / "system"
        self._pedalboards_dir: Path = self._root / "pedalboards"

        self._config_dir.mkdir()
        self._system_dir.mkdir()
        self._pedalboards_dir.mkdir()

        # Write factory content.
        (self._config_dir / "default_config.yml").write_text("# factory config\n")
        (self._config_dir / "settings.yml").write_text("# factory settings\n")
        (self._system_dir / "config.txt").write_text("# factory config.txt\n")
        (self._system_dir / "jackdrc").write_text("# factory jackdrc\n")
        for name in (
            "AmpBud.pedalboard",
            "Beths.pedalboard",
            "Carbon-Copy.pedalboard",
            "factory-defaults.pedalboard",
        ):
            (self._pedalboards_dir / name).mkdir()
            (self._pedalboards_dir / name / "manifest.ttl").write_text("# stub pedalboard\n")

        # Build real facets.
        clear_facets()
        self._config_facet = FileFacet(
            name="config",
            repo_dir=self._root / "config.git",
            files=("default_config.yml", "settings.yml"),
            source_resolver=lambda f: self._config_dir / f,
            display_name_resolver=lambda f: f,
        )
        self._boot_facet = FileFacet(
            name="boot",
            repo_dir=self._root / "system.git",
            files=("config.txt", "jackdrc"),
            source_resolver=lambda f: self._system_dir / f,
            display_name_resolver=lambda f: f,
        )
        self._pedalboard_facet = PedalboardFacet(self._pedalboards_dir)
        self._package_facet = EmulatorPackageFacet()
        register_facet("config", self._config_facet)
        register_facet("boot", self._boot_facet)
        register_facet("pedalboards", self._pedalboard_facet)
        register_facet("packages", self._package_facet)

        # Stamp config and boot so checkpoint mode has a stamp to roll back to.
        self._config_facet.stamp()
        self._boot_facet.stamp()

        # Modify some pedalboards and stamp them, simulating pi-stomp having
        # loaded them with user changes.  The stamp captures the modified state
        # (different from factory), so rollback-to-stamp and rollback-to-factory
        # are distinct operations.
        ampbud_manifest = self._pedalboards_dir / "AmpBud.pedalboard" / "manifest.ttl"
        ampbud_manifest.write_text("# AmpBud user preset\n")
        self._pedalboard_facet.stamp_item("AmpBud.pedalboard")
        beths_manifest = self._pedalboards_dir / "Beths.pedalboard" / "manifest.ttl"
        beths_manifest.write_text("# Beths user preset\n")
        self._pedalboard_facet.stamp_item("Beths.pedalboard")

        # Now modify some live files to simulate a dirty / already-changed device.
        (self._config_dir / "default_config.yml").write_text("# changed default config\n")
        (self._config_dir / "settings.yml").write_text("# changed settings\n")
        (self._system_dir / "config.txt").write_text("# changed config.txt\n")
        ampbud_manifest.write_text("# AmpBud further modified\n")

    def cleanup(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)

    def has_internet(self) -> bool:
        return True

    def refresh_package_db(self) -> None:
        pass

    def domains(self) -> tuple[tuple[str, str], ...]:
        return (
            ("pedalboards", "Pedalboards"),
            ("plugins", "Plugins"),
            ("config", "Config"),
            ("system", "System"),
        )

    def _facets_for(self, domain: str) -> list[Facet]:
        from pistomp_recovery.facet import all_facets
        facets = all_facets()
        return [f for key in DOMAIN_FACETS.get(domain, ()) if (f := facets.get(key)) is not None]

    def domain_items(self, mode: str, domain: str) -> list[Item]:
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
                        continue
                    if mode == "checkpoint" and not it.dirty:
                        continue
                    out.append(Item(it.name, it.label, it.dirty, it.right, actions))
        return out

    def install_packages(
        self,
        packages: list[str],
        progress: ProgressCallback,
    ) -> bool:
        """Simulate download + install on a worker thread."""

        def step(steps: int) -> None:
            for i in range(1, steps + 1):
                frac = i / steps
                progress(
                    "Downloading...",
                    frac * 0.5,
                    f"Downloading {packages[0]}... ({i}/{steps})",
                    False,
                )
                time.sleep(0.15)
            for i in range(1, steps + 1):
                frac = 0.5 + i / steps * 0.4
                progress(
                    "Installing...",
                    frac,
                    f"Installing {packages[0]}... ({i}/{steps})",
                    False,
                )
                time.sleep(0.15)

            for pkg in packages:
                update = next(
                    (u for u in self._package_facet.pending_updates() if u.name == pkg), None
                )
                if update:
                    self._package_facet.install(pkg, update.new_version)
                else:
                    logger.info("No pending update for %s", pkg)

            progress(
                "Update complete",
                1.0,
                "Done. Exit (\u25b6) to restart pi-Stomp.",
                True,
            )

        progress(
            "Downloading...",
            0.0,
            f"Downloading {len(packages)} package(s)...",
            False,
        )
        threading.Thread(target=step, args=(4,), daemon=True).start()
        return True


class EmulatorServiceBackend(ServiceBackend):
    """Stub system integration for the emulator."""

    def __init__(self, boot_mode: BootMode = BootMode.USER_RECOVERY) -> None:
        self._boot_mode: BootMode = boot_mode

    def stop_main_app(self) -> bool:
        return True

    def start_main_app(self) -> bool:
        logger.info("Resuming main app (emulated)")
        return True

    def restart_jack(self) -> bool:
        logger.info("Restarting JACK (emulated)")
        return True

    def restart_mod(self) -> bool:
        logger.info("Restarting MOD (emulated)")
        return True

    def diagnose_services(self, services: list[str]) -> CrashInfo:
        return CrashInfo(
            boot_mode=BootMode.USER_RECOVERY,
            failed_service=None,
            crash_log="",
            service_states={s: "active" for s in services},
        )

    def reboot(self) -> None:
        logger.info("Reboot (emulated)")

    def power_off(self) -> None:
        logger.info("Power off (emulated)")

    def recovery_sha(self) -> str:
        return "0a1b2c3"

    def crash_info(self) -> CrashInfo | None:
        if self._boot_mode != BootMode.CRASH_RECOVERY:
            return None
        return CrashInfo(
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


def make_emulator_backends(boot_mode: BootMode = BootMode.USER_RECOVERY) -> AppBackends:
    """Create emulator backends wired to real recovery facets on temp data."""
    return AppBackends(
        display=PygameDisplayBackend(),
        input=FakeInputBackend(FakeEncoderInput()),
        data=EmulatorDataBackend(),
        services=EmulatorServiceBackend(boot_mode),
    )
