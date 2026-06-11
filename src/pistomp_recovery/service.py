from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from enum import Enum, auto
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


def get_crash_log(lines: int = 10) -> str:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["journalctl", "-u", "mod-ala-pi-stomp", "-n", str(lines), "--no-pager"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def get_system_info() -> dict[str, str]:
    info: dict[str, str] = {}

    kernel_result: subprocess.CompletedProcess[str] = subprocess.run(
        ["uname", "-r"], capture_output=True, text=True
    )
    info["kernel"] = kernel_result.stdout.strip()

    uptime_result: subprocess.CompletedProcess[str] = subprocess.run(
        ["uptime", "-p"], capture_output=True, text=True
    )
    info["uptime"] = uptime_result.stdout.strip()

    temp_path: Path = Path("/sys/class/thermal/thermal_zone0/temp")
    if temp_path.exists():
        temp_mC: str = temp_path.read_text().strip()
        info["temp"] = f"{int(temp_mC) / 1000:.1f}°C"

    os_release: Path = Path("/etc/os-release")
    if os_release.exists():
        for line in os_release.read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                info["os"] = line.split("=", 1)[1].strip('"')

    for svc in PISTOMP_SERVICES:
        info[svc] = service_status(svc)

    return info
