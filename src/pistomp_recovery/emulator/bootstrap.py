"""Bootstrap the emulator — creates a live recovery UI in a pygame window.

Usage:
    python -m pistomp_recovery.emulator
    python -m pistomp_recovery.emulator --force-crash

Keyboard shortcuts:
    ← / →        navigate reticules (incl. the header back/exit icon)
    Enter/Space  select
    Esc          quit
"""

from __future__ import annotations

import argparse
import logging

import pygame

from pistomp_recovery.app import RecoveryAppCore
from pistomp_recovery.backends import AppBackends
from pistomp_recovery.emulator.backends import FakeInputBackend, make_emulator_backends
from pistomp_recovery.emulator.window import EmulatorWindow
from pistomp_recovery.service import BootMode, CrashInfo

logger = logging.getLogger(__name__)


class EmulatorApp:
    """Thin wrapper around `RecoveryAppCore` with a pygame window."""

    def __init__(self, boot_mode: BootMode = BootMode.USER_RECOVERY) -> None:
        self._backends: AppBackends = make_emulator_backends(boot_mode)
        crash_info: CrashInfo = self._backends.services.crash_info() or CrashInfo(
            boot_mode=boot_mode,
            failed_service=None,
            crash_log="",
            service_states={},
        )
        self._core: RecoveryAppCore = RecoveryAppCore(self._backends, crash_info)
        self._window: EmulatorWindow | None = None

    def init(self) -> None:
        assert isinstance(self._backends.input, FakeInputBackend)
        pygame.init()
        self._backends.display.init()
        self._window = EmulatorWindow(
            lcd_surface=self._core.surface,
            send_event=self._backends.input.inject_event,
        )
        self._core.init()
        logger.info(
            "Emulator initialized (boot mode: %s)",
            self._core._boot_mode.name,  # type: ignore[attr-defined]
        )

    @property
    def core(self) -> RecoveryAppCore:
        return self._core

    def run(self) -> None:
        assert self._window is not None
        self._core.run(
            pre_poll=self._window.process_events,
            post_draw=self._window.render,
        )


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="pistomp-recovery emulator"
    )
    parser.add_argument("--log", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--force-crash", action="store_true", help="Start in crash recovery mode")
    args: argparse.Namespace = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log),
        format="%(levelname)s:%(name)s:%(message)s",
    )

    boot_mode: BootMode = BootMode.CRASH_RECOVERY if args.force_crash else BootMode.USER_RECOVERY
    app: EmulatorApp = EmulatorApp(boot_mode)

    try:
        app.init()
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.core.cleanup()
        pygame.quit()


if __name__ == "__main__":
    main()
