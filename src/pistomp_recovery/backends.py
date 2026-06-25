"""Backend protocols for the recovery UI.

The recovery application is intentionally a black box around the device:
`RecoveryAppCore` owns the LCD menu flow and delegates every side effect to
injected backends.  Real device code uses SPI/GPIO/pacman/systemd
implementations; the emulator uses pygame, fake input, and in-memory stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

import pygame

from pistomp_recovery.items import Item
from pistomp_recovery.service import CrashInfo
from pistomp_recovery.ui.widgets.misc import Box, InputEvent


@runtime_checkable
class DisplayBackend(Protocol):
    """LCD bridge: a pygame Surface that can be flushed to hardware.

    ``update`` accepts an optional list of dirty rects (in surface
    coordinates). When ``rects`` is None or omitted the whole surface is
    pushed; otherwise backends may push only the union of the given rects
    to avoid a full-frame SPI transfer. ``transfer_ms`` estimates the cost
    of pushing a rect so the core can decide inline-vs-coalesce.
    """

    @property
    def surface(self) -> pygame.Surface: ...

    def init(self) -> None: ...

    def update(self, surface: pygame.Surface, rects: list[Box] | None = None) -> None: ...

    def transfer_ms(self, rect: Box | None = None) -> float:
        """Estimated milliseconds to push ``rect`` (or the whole panel)."""
        return 0.0


@runtime_checkable
class InputBackend(Protocol):
    """Encoder + switch input source."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def poll(self) -> list[InputEvent]: ...


ProgressCallback = Callable[[str, float, str, bool], None]


@runtime_checkable
class DataBackend(Protocol):
    """Source of recoverable domains and the actions that mutate them."""

    def domains(self, mode: str = "") -> tuple[tuple[str, str], ...]:
        """Return (domain_id, domain_label) pairs in menu order.

        ``mode`` is the recovery mode (``checkpoint``/``factory``/``updates``).
        Implementations may omit domains that have no items for a given mode
        (e.g. pedalboards/plugins have no installable updates, so they drop
        out of the Updates picker).  The default ignores mode and returns all.
        """
        ...

    def domain_items(self, mode: str, domain: str) -> list[Item]:
        """Items for a domain in the given mode (checkpoint/factory/updates)."""
        ...

    def domain_summary(self, mode: str, domain: str) -> str:
        """Optional right-aligned badge override for a domain in the picker.

        Returns "" to fall back to the default count badge. Used by the plugins
        domain to surface the on-disk cache size instead of a change count.
        """
        return ""

    def has_internet(self) -> bool:
        """Return True if the device can reach the internet.

        Used before entering the Updates picker to decide whether to attempt a
        package-DB sync.  Implementations should be fast (TCP probe with a
        short timeout).  The default returns True so non-network backends
        behave as if connectivity is always present.
        """
        return True

    def refresh_package_db(self) -> None:
        """Sync the distro package database (apt-get update / pacman -Sy).

        Called from a background thread by the UI before loading the Updates
        picker.  The default is a no-op.
        """

    def install_packages(
        self,
        packages: list[str],
        progress: ProgressCallback,
    ) -> bool:
        """Download, install, and stamp the given packages.

        Backends may run this on a worker thread; progress() must be safe to
        call from that thread.  The return value is True on success.
        """
        ...


@runtime_checkable
class ServiceBackend(Protocol):
    """System-level integration: lifecycle, crash info, and recovery build id."""

    def stop_main_app(self) -> bool: ...

    def start_main_app(self) -> bool: ...

    def restart_jack(self) -> bool: ...

    def restart_mod(self) -> bool: ...

    def diagnose_services(self, services: list[str]) -> CrashInfo:
        """Check current health of the given services; used after a restart."""
        ...

    def reboot(self) -> None: ...

    def power_off(self) -> None: ...

    def recovery_sha(self) -> str: ...

    def crash_info(self) -> CrashInfo | None:
        """Crash diagnostics when booting into recovery, or None if unavailable."""
        ...


@dataclass(frozen=True)
class AppBackends:
    """Container so entry points can inject all backends at once."""

    display: DisplayBackend
    input: InputBackend
    data: DataBackend
    services: ServiceBackend
