"""Entry point for the real recovery service on the pi-Stomp device."""

from __future__ import annotations

import argparse
import logging
import signal

from pistomp_recovery.app import RecoveryAppCore
from pistomp_recovery.backends_real import make_real_backends
from pistomp_recovery.facet import register_default_facets
from pistomp_recovery.service import BootMode, CrashInfo, diagnose_crash

logger = logging.getLogger(__name__)


def main(args: list[str] | None = None) -> None:
    desc = "pi-Stomp Recovery Service"
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=desc)
    parser.add_argument(
        "--log", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    parser.add_argument(
        "--force-crash", action="store_true", help="Force crash recovery mode"
    )
    parser.add_argument(
        "--force-menu", action="store_true", help="Force recovery menu mode"
    )
    parsed: argparse.Namespace = parser.parse_args(args)

    logging.basicConfig(
        level=getattr(logging, parsed.log),
        format="%(levelname)s:%(name)s:%(message)s",
    )

    # Snapshot crash state immediately — before stop_main_app() or Conflicts=
    # can transition services to inactive and wipe their Result property.
    crash_info: CrashInfo = diagnose_crash()
    logger.info(
        "boot_mode=%s failed_service=%s",
        crash_info.boot_mode.name,
        crash_info.failed_service,
    )
    if parsed.force_crash:
        crash_info.boot_mode = BootMode.CRASH_RECOVERY
    elif parsed.force_menu:
        crash_info.boot_mode = BootMode.USER_RECOVERY

    register_default_facets()
    backends = make_real_backends()
    app: RecoveryAppCore = RecoveryAppCore(backends, crash_info)

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
