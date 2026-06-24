from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from enum import Enum, auto
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from pistomp_recovery.constants import PISTOMP_SERVICES
from pistomp_recovery.packages.health import service_journal, service_last_result, service_status

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
    return diagnose_services(chain)


def _service_crashed(state: str, name: str) -> bool:
    """True if the service is currently failed or last exited with an error.

    systemd transitions a failed unit from 'failed' → 'inactive' when it is
    stopped (e.g. to satisfy Conflicts= in the recovery unit), so we can't rely
    on ActiveState alone.  The Result property is only reset on *start*, so it
    still reflects a crash even after the state becomes 'inactive'.
    """
    if state == "failed":
        return True
    if state == "inactive":
        return service_last_result(name) not in ("", "success")
    return False


def diagnose_services(services: list[str]) -> CrashInfo:
    """Check the current health of the given services."""
    states: dict[str, str] = {}
    failed_service: str | None = None
    for svc in services:
        state = service_status(svc)
        states[svc] = state
        if failed_service is None and _service_crashed(state, svc):
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
    return diagnose_crash().boot_mode


def stop_main_app() -> bool:
    """
    Redundant under systemd (unit Conflicts= already stops main); the safety
    net for launching recovery directly, where no conflict is enforced.
    """
    logger.info("Stopping mod-ala-pi-stomp")
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["sudo", "systemctl", "stop", "mod-ala-pi-stomp"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def start_main_app() -> bool:
    """Start the pi-Stomp service stack and let recovery exit.

    We must unload ourselves before services with `Conflicts=` can start.
    ``--no-block``just queues them: when we exit, they are unblocked.
    """
    logger.info("Resetting failure state and starting mod-ala-pi-stomp")
    for svc in PISTOMP_SERVICES:
        subprocess.run(["sudo", "systemctl", "reset-failed", svc], check=False)

    for svc in PISTOMP_SERVICES:
        if svc == "mod-ala-pi-stomp":
            continue
        subprocess.run(["sudo", "systemctl", "start", "--no-block", svc], check=False)

    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["sudo", "systemctl", "start", "--no-block", "mod-ala-pi-stomp"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def restart_jack() -> bool:
    """Restart the JACK audio server."""
    logger.info("Restarting jack")
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["sudo", "systemctl", "restart", "jack"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def restart_mod() -> bool:
    """Restart the mod-host service, which runs audio."""
    logger.info("Restarting mod-host")
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["sudo", "systemctl", "restart", "mod-host"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


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
