from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from enum import Enum, auto
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from pistomp_recovery.constants import PISTOMP_SERVICES
from pistomp_recovery.packages.health import service_journal, service_status

logger = logging.getLogger(__name__)


class BootMode(Enum):
    NORMAL = auto()
    CRASH_RECOVERY = auto()
    USER_RECOVERY = auto()


@dataclass
class CrashInfo:
    boot_mode: BootMode
    failed_service: str | None
    crash_log: str
    service_states: dict[str, str]


def diagnose_crash() -> CrashInfo:
    """Determine why recovery was triggered."""
    chain: list[str] = ["jack", "mod-host", "mod-ui", "mod-ala-pi-stomp"]
    states: dict[str, str] = {}
    failed_service: str | None = None
    for svc in chain:
        states[svc] = service_status(svc)
        if states[svc] == "failed" and failed_service is None:
            failed_service = svc

    crash_log: str = ""
    if failed_service:
        crash_log = service_journal(failed_service, lines=10)

    boot_mode = BootMode.CRASH_RECOVERY if failed_service else BootMode.USER_RECOVERY
    return CrashInfo(
        boot_mode=boot_mode,
        failed_service=failed_service,
        crash_log=crash_log,
        service_states=states,
    )


def get_boot_mode() -> BootMode:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["systemctl", "is-failed", "mod-ala-pi-stomp"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() == "failed":
        return BootMode.CRASH_RECOVERY
    return BootMode.USER_RECOVERY


def stop_main_app() -> bool:
    """
    Redundant under systemd (unit Conflicts= already stops main); the safety
    net for launching recovery directly, where no conflict is enforced.
    """
    logger.info("Stopping mod-ala-pi-stomp")
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["systemctl", "stop", "mod-ala-pi-stomp"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def start_main_app() -> bool:
    logger.info("Resetting failure state and starting mod-ala-pi-stomp")
    subprocess.run(["systemctl", "reset-failed", "mod-ala-pi-stomp"], check=False)

    for svc in PISTOMP_SERVICES:
        if svc != "mod-ala-pi-stomp":
            subprocess.run(["systemctl", "start", svc], check=False)

    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["systemctl", "start", "mod-ala-pi-stomp"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def restart_jack() -> bool:
    """Restart the JACK audio server."""
    logger.info("Restarting jack")
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["systemctl", "restart", "jack"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def restart_mod() -> bool:
    """Restart the MOD stack (mod-host, mod-ui, the pi-stomp app)."""
    logger.info("Restarting mod stack")
    ok: bool = True
    for svc in ("mod-host", "mod-ui", "mod-ala-pi-stomp"):
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["systemctl", "restart", svc],
            capture_output=True,
            text=True,
        )
        ok = ok and result.returncode == 0
    return ok


def recovery_sha() -> str:
    """Return a 7-char identifier for this recovery build (git sha or version)."""
    try:
        out: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except OSError:
        pass
    try:
        return _pkg_version("pistomp-recovery")[:7]
    except PackageNotFoundError:
        return "unknown"


