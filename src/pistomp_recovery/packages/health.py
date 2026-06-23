from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def service_status(name: str) -> str:
    """Returns 'active', 'failed', 'inactive', etc."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def service_last_result(name: str) -> str:
    """Return the result of the last run: 'success', 'exit-code', 'signal', etc.

    Unlike ActiveState, Result is only reset when the service is *started* — not
    when it's stopped.  This lets us detect a crash even after systemd transitions
    the unit from 'failed' to 'inactive' (e.g. via Conflicts= in the recovery unit).
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["systemctl", "show", name, "--property=Result", "--value"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def service_journal(name: str, lines: int = 10) -> str:
    """Returns recent journal lines for a service."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["journalctl", "-u", name, "-n", str(lines), "--no-pager"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
