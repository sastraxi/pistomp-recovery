"""Tests for boot-mode detection and crash diagnosis."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pistomp_recovery.service import (
    BootMode,
    _service_crashed,
    diagnose_services,
    get_boot_mode,
)


# ---------------------------------------------------------------------------
# _service_crashed
# ---------------------------------------------------------------------------


def test_service_crashed_failed_state() -> None:
    """ActiveState=failed is always a crash regardless of Result."""
    assert _service_crashed("failed", "jack") is True


def test_service_crashed_inactive_with_bad_result() -> None:
    """ActiveState=inactive + Result=exit-code means Conflicts= cleared a failed unit."""
    with patch("pistomp_recovery.service.service_last_result", return_value="exit-code"):
        assert _service_crashed("inactive", "jack") is True


def test_service_crashed_inactive_with_signal() -> None:
    with patch("pistomp_recovery.service.service_last_result", return_value="signal"):
        assert _service_crashed("inactive", "mod-host") is True


def test_service_crashed_inactive_clean_stop() -> None:
    """ActiveState=inactive + Result=success means a clean stop, not a crash."""
    with patch("pistomp_recovery.service.service_last_result", return_value="success"):
        assert _service_crashed("inactive", "jack") is False


def test_service_crashed_inactive_no_result() -> None:
    """ActiveState=inactive + empty Result means service never ran."""
    with patch("pistomp_recovery.service.service_last_result", return_value=""):
        assert _service_crashed("inactive", "jack") is False


def test_service_crashed_active() -> None:
    with patch("pistomp_recovery.service.service_last_result", return_value="success"):
        assert _service_crashed("active", "jack") is False


# ---------------------------------------------------------------------------
# diagnose_services
# ---------------------------------------------------------------------------


def test_diagnose_services_picks_first_failed() -> None:
    """The most foundational (earliest in the chain) failed service is reported."""
    with (
        patch("pistomp_recovery.service.service_status") as mock_status,
        patch("pistomp_recovery.service.service_last_result", return_value="exit-code"),
        patch("pistomp_recovery.service.service_journal", return_value="audio: no card"),
    ):
        mock_status.side_effect = lambda svc: (
            "failed" if svc == "jack" else "inactive"
        )
        info = diagnose_services(["jack", "mod-host", "mod-ui", "mod-ala-pi-stomp"])

    assert info.boot_mode == BootMode.CRASH_RECOVERY
    assert info.failed_service == "jack"
    assert info.service_states["mod-host"] == "inactive"


def test_diagnose_services_detects_crash_via_result() -> None:
    """Crash is detected even when Conflicts= has already cleared ActiveState to inactive."""

    def _status(svc: str) -> str:
        return "inactive"  # Conflicts= stopped everything

    def _result(svc: str) -> str:
        return "exit-code" if svc == "mod-ala-pi-stomp" else "success"

    with (
        patch("pistomp_recovery.service.service_status", side_effect=_status),
        patch("pistomp_recovery.service.service_last_result", side_effect=_result),
        patch("pistomp_recovery.service.service_journal", return_value=""),
    ):
        info = diagnose_services(["jack", "mod-host", "mod-ui", "mod-ala-pi-stomp"])

    assert info.boot_mode == BootMode.CRASH_RECOVERY
    assert info.failed_service == "mod-ala-pi-stomp"


def test_diagnose_services_no_crash() -> None:
    """All services active → USER_RECOVERY, no failed service."""
    with (
        patch("pistomp_recovery.service.service_status", return_value="active"),
        patch("pistomp_recovery.service.service_last_result", return_value="success"),
    ):
        info = diagnose_services(["jack", "mod-host", "mod-ui", "mod-ala-pi-stomp"])

    assert info.boot_mode == BootMode.USER_RECOVERY
    assert info.failed_service is None


# ---------------------------------------------------------------------------
# get_boot_mode
# ---------------------------------------------------------------------------


def test_get_boot_mode_crash_when_jack_stopped_after_crash() -> None:
    """get_boot_mode returns CRASH_RECOVERY even if jack is only 'inactive' post-crash."""
    with (
        patch("pistomp_recovery.service.service_status", return_value="inactive"),
        patch("pistomp_recovery.service.service_last_result") as mock_result,
        patch("pistomp_recovery.service.service_journal", return_value=""),
    ):
        mock_result.side_effect = lambda svc: "exit-code" if svc == "jack" else "success"
        assert get_boot_mode() == BootMode.CRASH_RECOVERY


def test_get_boot_mode_user_recovery_when_all_clean() -> None:
    with (
        patch("pistomp_recovery.service.service_status", return_value="inactive"),
        patch("pistomp_recovery.service.service_last_result", return_value="success"),
    ):
        assert get_boot_mode() == BootMode.USER_RECOVERY
