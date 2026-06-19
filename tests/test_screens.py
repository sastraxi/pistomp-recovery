# pyright: reportPrivateUsage=false
"""Integration tests that drive the recovery app via fake backends.

Each test asserts behavior (navigation, confirm, progress) and captures
snapshots of the rendered frame at key transitions to catch visual
regressions. Run with --snapshot-update to regenerate snapshots.
"""

from __future__ import annotations

import time
from typing import Callable

from pistomp_recovery.app import RecoveryAppCore
from pistomp_recovery.backends import AppBackends
from pistomp_recovery.items import Action, Item, PackageUpdate, Row, Target
from pistomp_recovery.service import BootMode, CrashInfo
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.widgets.header import ICON_BACK, ICON_EXIT
from pistomp_recovery.ui.widgets.misc import InputEvent
from tests.conftest import (
    AppHarness,
    FakeDataBackend,
    FakeDisplayBackend,
    FakeInputBackend,
    FakeServiceBackend,
)


def test_badge_excludes_update_all() -> None:
    assert RecoveryAppCore.badge("updates", 3, all_item=True) == "2 available"
    assert RecoveryAppCore.badge("updates", 2, all_item=False) == "2 available"
    assert RecoveryAppCore.badge("updates", 1, all_item=True) == ""
    assert RecoveryAppCore.badge("updates", 0, all_item=False) == ""
    assert RecoveryAppCore.badge("checkpoint", 3, all_item=True) == "3 changed"


def test_domain_screen_refreshes_after_successful_action(
    recovery_app: AppHarness,
    fake_data: FakeDataBackend,
) -> None:
    """After a successful action the current domain list is rebuilt from fresh data."""
    harness = recovery_app
    # Keep the main menu on the stack so pop returns somewhere sensible.
    harness.app._screen_stack[:] = [harness.app._screen_stack[0]]

    first = PackageUpdate("a", "0.1", "0.2")
    fake_data.set_updates("system", [first])
    fake_data._install_progress = [
        ("Update complete", 1.0, "Done.", True),
    ]
    harness.app._show_domain("updates", "system")
    harness.inject()
    assert harness.row_labels() == ["a 0.1"]

    # Click the update item, confirm the dialog, then dismiss the done screen.
    harness.select("a 0.1")
    harness.inject(InputEvent.RIGHT, InputEvent.CLICK, InputEvent.CLICK)

    # Dismissing the done screen should re-query the domain. Because the
    # domain is now empty, the app pops back to the menu below it.
    assert fake_data._installed == [["a"]]  # type: ignore[attr-defined]
    assert harness.row_labels() == [
        "Restart Jack",
        "Restart MOD",
        "Reset to Checkpoint",
        "Factory Reset",
        "Updates",
        "Reboot",
        "Power Off",
    ]


def _push(harness: AppHarness, title: str, rows: list[Row], back: bool) -> MenuScreen:
    icon = Target(ICON_BACK if back else ICON_EXIT, harness.app.pop_screen)
    screen = MenuScreen(harness.app.surface, title, rows, icon)
    harness.app.push_screen(screen)
    return screen


def test_main_menu_renders(recovery_app: AppHarness, snapshot: Callable[..., None]) -> None:
    """The root menu shows the inverted title, exit icon, and top-level rows."""
    harness = recovery_app
    harness.inject()
    snapshot()

    labels = harness.nav_labels()
    assert labels[0] == ICON_EXIT  # header icon is exit on the root menu
    assert "Restart Jack" in labels and "Restart MOD" in labels
    assert "Reset to Checkpoint" in labels
    assert "Reboot" in labels and "Power Off" in labels


def test_submenu_has_back_icon(recovery_app: AppHarness, snapshot: Callable[..., None]) -> None:
    """Sub-screens carry a back icon in the header instead of an exit icon."""
    harness = recovery_app
    harness.app._screen_stack.clear()
    _push(
        harness,
        "Pedalboards",
        [Row((Target("foo.pedalboard", lambda: None, enabled=False),), right="factory")],
        back=True,
    )
    harness.inject()
    snapshot()

    assert harness.nav_labels()[0] == ICON_BACK


def test_disabled_target_skipped(recovery_app: AppHarness) -> None:
    """Disabled targets render but are not reachable by the encoder."""
    harness = recovery_app
    harness.app._screen_stack.clear()
    _push(
        harness,
        "Plugins",
        [Row((Target("No updates", lambda: None, enabled=False),))],
        back=True,
    )
    harness.inject()
    # Only the header icon is navigable.
    assert harness.nav_labels() == [ICON_BACK]
    assert harness.row_labels() == ["No updates"]


def test_confirm_cancel(recovery_app: AppHarness, snapshot: Callable[..., None]) -> None:
    harness = recovery_app
    called: list[bool] = []
    harness.app._screen_stack.clear()
    screen = _push(
        harness,
        "Factory Reset",
        [Row((Target("jackdrc", lambda: called.append(True), confirm="Reset jackdrc?"),))],
        back=True,
    )
    harness.inject()
    snapshot("list")

    harness.select("jackdrc")
    assert screen._state == "CONFIRM"
    snapshot("confirm")

    harness.inject(InputEvent.CLICK)  # No is focused by default -> cancel
    assert screen._state == "LIST"
    assert called == []
    snapshot("cancelled")


def test_confirm_confirm(recovery_app: AppHarness, snapshot: Callable[..., None]) -> None:
    harness = recovery_app
    called: list[bool] = []
    harness.app._screen_stack.clear()
    screen = _push(
        harness,
        "Factory Reset",
        [Row((Target("jackdrc", lambda: called.append(True), confirm="Reset jackdrc?"),))],
        back=True,
    )
    harness.inject()

    harness.select("jackdrc")
    assert screen._state == "CONFIRM"
    harness.inject(InputEvent.RIGHT, InputEvent.CLICK)  # move to Yes, confirm
    assert called == [True]
    assert screen._state == "LIST"
    snapshot("confirmed")


def test_progress_blocks_then_dismisses(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    harness = recovery_app
    harness.app._screen_stack.clear()
    screen = _push(harness, "Updates", [], back=True)

    screen.set_progress("Downloading...", 0.5, "Downloading 2 package(s)...")
    harness.inject()
    snapshot("progress")
    assert screen._state == "PROGRESS"

    # Input is blocked while in progress.
    harness.inject(InputEvent.RIGHT, InputEvent.CLICK, InputEvent.LONG_CLICK)
    assert screen._state == "PROGRESS"

    # Once marked done, a click dismisses back to the list.
    screen.set_progress("Update complete", 1.0, "Done.", done=True)
    harness.redraw()
    snapshot("done")
    harness.inject(InputEvent.CLICK)
    assert screen._state == "LIST"


def test_update_picker_excludes_all_from_count(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """The Updates picker badge counts real updates, not the synthetic Update All."""
    harness = recovery_app
    harness.app._screen_stack.clear()
    items = [
        Item("a", "a 0.1", False, "↑0.2", [Action("Update", lambda: None)]),
        Item("b", "b 0.3", False, "↑0.4", [Action("Update", lambda: None)]),
        Item("all", "Update All", False, "", [Action("Update All", lambda: None)]),
    ]
    count = len(items)
    has_all = items[-1].name == "all"
    badge = RecoveryAppCore.badge("updates", count, all_item=has_all)
    _push(
        harness,
        "Updates",
        [Row((Target("System", lambda: None),), right=badge)],
        back=True,
    )
    harness.inject()
    snapshot("picker")

    # Two real updates plus Update All is still reported as 2 available.
    menu = harness._menu()
    assert menu is not None
    assert menu._rows[0].right == "2 available"

    # Domain detail rows still render all items, including Update All.
    _push(
        harness,
        "System",
        [Row((Target(it.label, lambda: None),), right=it.right) for it in items],
        back=True,
    )
    harness.inject()
    snapshot("domain_list")
    assert harness.row_labels() == ["a 0.1", "b 0.3", "Update All"]


def test_update_items_are_selectable_with_empty_actions(
    recovery_app: AppHarness,
) -> None:
    """Update items with no actions must still be selectable (not disabled)."""
    harness = recovery_app
    harness.app._screen_stack.clear()
    fake_data = harness.app._backends.data
    assert isinstance(fake_data, FakeDataBackend)
    fake_data.set_updates(
        "system",
        [PackageUpdate("a", "0.1", "0.2"), PackageUpdate("b", "0.3", "0.4")],
    )
    harness.app._show_domain("updates", "system")
    harness.inject()

    menu = harness._menu()
    assert menu is not None
    assert harness.row_labels() == ["a 0.1", "b 0.3"]
    # All update items should be navigable (enabled) even with empty actions.
    assert all(target.enabled for row in menu._rows for target in row.targets)


def test_picker_badge_refreshes_after_domain_action(
    recovery_app: AppHarness,
) -> None:
    """After a 3rd-level domain action the 2nd-level picker badges update."""
    harness = recovery_app
    harness.inject()

    # Set up one dirty pedalboard so the picker shows a badge.
    fake_data = harness.app._backends.data
    assert isinstance(fake_data, FakeDataBackend)

    def clear_pedalboards() -> None:
        fake_data.set_items("checkpoint", "pedalboards", [])

    dirty = Item(
        "dirty.pedalboard",
        "dirty.pedalboard",
        True,
        "2d ago",
        [Action("Rollback to stamp", clear_pedalboards)],
    )
    fake_data.set_items("checkpoint", "pedalboards", [dirty])

    harness.select("Reset to Checkpoint")
    picker = harness._menu()
    assert picker is not None
    assert picker._rows[0].right == "1 changed"

    harness.select("Pedalboards")
    harness.select("dirty.pedalboard")

    # The wrapped action cleared the domain and the domain was popped; the
    # picker badge should now reflect the new (empty) state.
    assert picker._rows[0].right == ""


def test_reset_picker_navigation(recovery_app: AppHarness) -> None:
    """RESET TO CHECKPOINT drills into the shared domain picker."""
    harness = recovery_app
    harness.inject()
    harness.select("Reset to Checkpoint")

    labels = harness.row_labels()
    assert labels == ["Pedalboards", "Plugins", "Config", "System"]

    # Plugins is selectable but leads to an empty list.
    harness.select("Plugins")
    assert harness.row_labels() == ["No updates"] or harness.row_labels() == ["Nothing to reset"]


def test_crash_recovery_boot(
    fake_display: FakeDisplayBackend,
    fake_input: FakeInputBackend,
    fake_data: FakeDataBackend,
) -> None:
    """Booting in crash mode shows the crash screen."""
    services = FakeServiceBackend(boot_mode=BootMode.CRASH_RECOVERY)
    app = RecoveryAppCore(
        AppBackends(
            display=fake_display,
            input=fake_input,
            data=fake_data,
            services=services,
        ),
        BootMode.CRASH_RECOVERY,
    )
    app.init()
    screen = app.current_screen()
    from pistomp_recovery.ui.screens.crash import CrashScreen

    assert isinstance(screen, CrashScreen)
    app.cleanup()


def test_resume_starts_main_app(
    fake_display: FakeDisplayBackend,
    fake_input: FakeInputBackend,
    fake_data: FakeDataBackend,
) -> None:
    """Selecting exit on the root menu starts the main app and stops the loop."""
    services = FakeServiceBackend()
    app = RecoveryAppCore(
        AppBackends(
            display=fake_display,
            input=fake_input,
            data=fake_data,
            services=services,
        ),
        BootMode.USER_RECOVERY,
    )
    app.init()
    # Navigate to the exit icon (header target) and select it.
    app.handle_event(InputEvent.LEFT)
    app.handle_event(InputEvent.CLICK)
    assert "start_main_app" in services.calls
    assert not app.running
    app.cleanup()


def _wait_for_restart(harness: AppHarness) -> None:
    """Block until the restart worker thread completes and the UI is dirty."""
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        time.sleep(0.01)
        if harness.app._dirty:
            harness.redraw()
            return
    raise TimeoutError("Restart worker did not complete in time")


def test_restart_jack_success(
    recovery_app: AppHarness,
    fake_services: FakeServiceBackend,
    snapshot: Callable[..., None],
) -> None:
    """Clicking Jack shows progress, then a done message when the service comes up."""
    harness = recovery_app
    harness.inject()

    harness.select("Restart Jack")

    # Wait for the restart thread to finish (fake backend is instant).
    _wait_for_restart(harness)

    assert "restart_jack" in fake_services.calls
    assert any("diagnose_services:jack" in c for c in fake_services.calls)

    # Thread reported success → menu is in PROGRESS done state.
    menu = harness._menu()
    assert menu is not None
    assert menu._state == "PROGRESS"
    assert menu._progress_done
    snapshot("done")

    # Click to dismiss → back to the list.
    harness.inject(InputEvent.CLICK)
    assert menu._state == "LIST"


def test_restart_jack_failure(
    fake_display: FakeDisplayBackend,
    fake_input: FakeInputBackend,
    fake_data: FakeDataBackend,
    snapshot: Callable[..., None],
) -> None:
    """When Jack fails to restart, a result screen with service states is shown."""
    failing_diagnosis = CrashInfo(
        boot_mode=BootMode.CRASH_RECOVERY,
        failed_service="jack",
        crash_log="ALSA: cannot find card\nJACK: server failed",
        service_states={"jack": "failed"},
    )
    services = FakeServiceBackend(restart_diagnosis=failing_diagnosis)
    app = RecoveryAppCore(
        AppBackends(
            display=fake_display,
            input=fake_input,
            data=fake_data,
            services=services,
        ),
        BootMode.USER_RECOVERY,
    )
    app.init()
    harness = AppHarness(app, fake_display)
    harness.inject()

    harness.select("Restart Jack")

    # Wait for thread to push the failure screen.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(app._screen_stack) < 2:
        time.sleep(0.01)
    harness.redraw()

    # A new screen should have been pushed.
    assert len(app._screen_stack) == 2
    result_screen = app.current_screen()
    assert isinstance(result_screen, MenuScreen)
    assert "Jack" in result_screen._title
    assert "Failed" in result_screen._title
    snapshot("failure_screen")

    # The result screen shows BACK and RETRY actions.
    labels = harness.nav_labels()
    assert "BACK" in labels
    assert "RETRY" in labels

    # BACK pops back to the main menu.
    harness.select("BACK")
    assert len(app._screen_stack) == 1
    snapshot("after_back")

    app.cleanup()
