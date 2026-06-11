"""Integration tests that drive the real RecoveryApp via fake hardware.

Each test asserts behavior (state machine, navigation) and captures snapshots
of the rendered frame at key transitions to catch visual regressions.
"""

from __future__ import annotations

from typing import Callable

import pytest

from pistomp_recovery.items import Action, Item
from pistomp_recovery.ui.screens.menu_screen import MenuScreen
from pistomp_recovery.ui.widgets.misc import InputEvent
from tests.conftest import AppHarness


def test_main_menu_no_back_item(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """Main Menu has no <- Back because it's the root screen."""
    harness = recovery_app
    harness.inject()  # ensure a frame is captured
    snapshot()

    menu = harness._current_menu()
    assert menu is not None
    labels = [item[0] for item in menu.items]
    assert not any("Back" in lbl for lbl in labels)


def test_sub_screen_shows_back_item(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """All sub-screens show a <- Back item."""
    harness = recovery_app

    harness.app._screen_stack.clear()
    screen = MenuScreen(
        harness.surface,
        title="Pedalboards",
        items=[
            Item(
                name="foo.pedalboard",
                label="foo.pedalboard",
                dirty=False,
                right="factory",
                actions=[],
            ),
        ],
        back_callback=harness.app._pop_screen,
    )
    harness.app._push_screen(screen)
    harness.inject()
    snapshot()

    menu = harness._current_menu()
    assert menu is not None
    labels = [item[0] for item in menu.items]
    assert any("Back" in lbl for lbl in labels)


def test_navigate_to_detail_and_back(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """Click an item to enter DETAIL, then long-press to return to LIST."""
    harness = recovery_app

    harness.app._screen_stack.clear()
    screen = MenuScreen(
        harness.surface,
        title="Packages",
        items=[
            Item(
                name="jack2-pistomp",
                label="jack2-pistomp",
                dirty=True,
                right="↑1.9.13",
                actions=[
                    Action("Update to 1.9.13", lambda: None, confirm="Update?"),
                    Action("Rollback to stamp", lambda: None, confirm="Rollback?"),
                ],
            ),
        ],
        back_callback=harness.app._pop_screen,
    )
    harness.app._push_screen(screen)
    harness.inject()
    snapshot("list")

    # Scroll to and select the item -> DETAIL
    harness.select("jack2")
    assert screen._state == "DETAIL"
    snapshot("detail")

    # Long-press back to LIST
    harness.long_press()
    assert screen._state == "LIST"
    snapshot("back_to_list")


def test_confirm_dialog_cancel(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """Enter DETAIL, select an action with confirm, then cancel."""
    harness = recovery_app

    harness.app._screen_stack.clear()
    screen = MenuScreen(
        harness.surface,
        title="Packages",
        items=[
            Item(
                name="jack2-pistomp",
                label="jack2-pistomp",
                dirty=False,
                right="",
                actions=[
                    Action("Rollback to factory", lambda: None,
                          confirm="Factory reset?"),
                ],
            ),
        ],
        back_callback=harness.app._pop_screen,
    )
    harness.app._push_screen(screen)
    harness.inject()
    snapshot("list")

    harness.select("jack2")
    assert screen._state == "DETAIL"
    snapshot("detail")

    # Select the rollback action -> enters CONFIRM
    harness.select("Rollback to factory")
    assert screen._state == "CONFIRM"
    snapshot("confirm")

    # Long-press cancels, returns to DETAIL
    harness.long_press()
    assert screen._state == "DETAIL"
    snapshot("cancelled")


def test_confirm_dialog_confirm(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """Enter CONFIRM and actually confirm the action."""
    harness = recovery_app
    called: bool = False

    def on_confirm() -> None:
        nonlocal called
        called = True

    harness.app._screen_stack.clear()
    screen = MenuScreen(
        harness.surface,
        title="Packages",
        items=[
            Item(
                name="jack2-pistomp",
                label="jack2-pistomp",
                dirty=False,
                right="",
                actions=[
                    Action("Rollback to factory", on_confirm,
                          confirm="Factory reset?"),
                ],
            ),
        ],
        back_callback=harness.app._pop_screen,
    )
    harness.app._push_screen(screen)
    harness.inject()

    harness.select("jack2")
    harness.select("Rollback to factory")
    assert screen._state == "CONFIRM"
    snapshot("confirm")

    # Move to Confirm button and click it
    harness.inject(InputEvent.RIGHT, InputEvent.CLICK)
    assert called is True
    assert screen._state == "DETAIL"
    snapshot("confirmed")


def test_progress_blocks_input(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """During PROGRESS state, input is consumed but does nothing."""
    harness = recovery_app

    harness.app._screen_stack.clear()
    screen = MenuScreen(
        harness.surface,
        title="Updates",
        items=[],
        back_callback=harness.app._pop_screen,
    )
    harness.app._push_screen(screen)
    screen.set_progress("Downloading...", 0.5, "Downloading 2 packages...")
    harness.inject()
    snapshot("progress")

    assert screen._state == "PROGRESS"

    # Try to navigate — should be blocked, state stays PROGRESS
    harness.inject(InputEvent.RIGHT, InputEvent.CLICK, InputEvent.LONG_CLICK)
    assert screen._state == "PROGRESS"


def test_main_menu_dirty_badge(
    recovery_app: AppHarness, snapshot: Callable[..., None]
) -> None:
    """Main menu shows dirty counts in right column when items are dirty."""
    harness = recovery_app

    harness.app._screen_stack.clear()
    screen = MenuScreen(
        harness.surface,
        title="Recovery",
        items=[
            Item("resume", "Resume", False, "",
                 [Action("Resume", lambda: None)]),
            Item("reset", "Reset...", True, "3 changed",
                 [Action("Open", lambda: None)]),
            Item("update", "Update...", False, "2 available",
                 [Action("Open", lambda: None)]),
        ],
        back_callback=None,
    )
    harness.app._push_screen(screen)
    harness.inject()
    snapshot()

    menu = harness._current_menu()
    assert menu is not None
    labels = [item[0] for item in menu.items]
    assert "Reset... *" in labels  # dirty marker appended by MenuScreen
    rights = [item[2] for item in menu.items]
    assert "3 changed" in rights
    assert "2 available" in rights
