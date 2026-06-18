"""Saga tests — end-to-end domain actions using real emulator backends.

These test the full action pipeline: navigate to a domain item → confirm →
action fires → screen refreshes → file state changes.  They use
``EmulatorDataBackend`` (real stubs) so the facet actions actually modify
live files and stamps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pistomp_recovery.app import RecoveryAppCore
from pistomp_recovery.backends import AppBackends
from pistomp_recovery.emulator.backends import (
    EmulatorDataBackend,
    EmulatorServiceBackend,
    FakeInputBackend,
    PygameDisplayBackend,
)
from pistomp_recovery.emulator.controls import FakeEncoderInput
from pistomp_recovery.service import BootMode
from pistomp_recovery.ui.widgets.misc import InputEvent
from tests.conftest import AppHarness


@pytest.fixture
def emulator_harness() -> AppHarness:
    display = PygameDisplayBackend()
    encoder = FakeEncoderInput()
    inp = FakeInputBackend(encoder)
    data = EmulatorDataBackend()
    services = EmulatorServiceBackend(BootMode.USER_RECOVERY)

    app = RecoveryAppCore(
        AppBackends(display=display, input=inp, data=data, services=services),
        BootMode.USER_RECOVERY,
    )
    app.init()
    harness = AppHarness(app, display)
    yield harness
    app.cleanup()


class TestFactoryResetConfig:
    """Factory Reset → Config → settings.yml → confirm → file restored."""

    def test_factory_reset_restores_modified_file(self, emulator_harness: AppHarness) -> None:
        harness = emulator_harness
        data = harness.app._backends.data
        assert isinstance(data, EmulatorDataBackend)

        # settings.yml was overwritten by EmulatorDataBackend after factory
        # snapshot — the live file reads "# changed settings\n", factory is
        # "# factory settings\n".
        settings = data._config_dir / "settings.yml"
        assert settings.read_text() == "# changed settings\n"

        # Root → Factory Reset → Config
        harness.select("Factory Reset")
        harness.inject()

        harness.select("Config")
        harness.inject()
        rows = harness.row_labels()
        assert any("settings.yml" in r for r in rows), f"settings.yml not in {rows}"

        # Navigate to settings.yml and confirm the rollback.
        harness.select("settings.yml")
        harness.inject()
        harness.inject(InputEvent.RIGHT, InputEvent.CLICK)  # Yes
        harness.inject(InputEvent.CLICK)                     # dismiss done
        harness.inject()

        # File should be restored to factory content.
        assert settings.read_text() == "# factory settings\n", (
            f"expected factory content, got: {settings.read_text()!r}"
        )

    def test_checkpoint_shows_dirty_after_file_change(self, emulator_harness: AppHarness) -> None:
        """Modify a file → checkpoint should show it as dirty."""
        harness = emulator_harness
        data = harness.app._backends.data
        assert isinstance(data, EmulatorDataBackend)

        settings = data._config_dir / "settings.yml"
        settings.write_text("# changed\n")

        harness.select("Reset to Checkpoint")
        harness.inject()
        harness.select("Config")
        harness.inject()
        rows = harness.row_labels()
        assert any("settings.yml" in r for r in rows), f"expected settings.yml in {rows}"
        assert any("*" in r for r in rows), f"expected dirty marker in {rows}"

    def test_stamp_and_rollback_pedalboard(self, emulator_harness: AppHarness) -> None:
        """Stamp a pedalboard via the CLI path, then rollback via the checkpoint menu."""
        harness = emulator_harness
        data = harness.app._backends.data
        assert isinstance(data, EmulatorDataBackend)

        # Get a pedalboard and modify it.
        pb_dir = data._pedalboards_dir / "AmpBud.pedalboard"
        manifest = pb_dir / "manifest.ttl"
        manifest.write_text("# modified by user\n")

        # Stamp it (as pi-stomp would).
        data._pedalboard_facet.stamp_item("AmpBud.pedalboard")

        # Modify again so it's dirty vs stamp.
        manifest.write_text("# further modified\n")

        # Navigate: Reset to Checkpoint → Pedalboards
        harness.select("Reset to Checkpoint")
        harness.inject()
        harness.select("Pedalboards")
        harness.inject()

        # Check dirty state BEFORE clicking into the item.
        rows = harness.row_labels()
        assert any("AmpBud.pedalboard" in r for r in rows)

        # Click into the pedalboard — shows confirm dialog (single action in checkpoint mode).
        harness.select("AmpBud.pedalboard")
        harness.inject()
        harness.inject(InputEvent.RIGHT, InputEvent.CLICK)  # Yes
        harness.inject(InputEvent.CLICK)                     # dismiss done
        harness.inject()

        assert manifest.read_text() == "# modified by user\n", (
            "pedalboard was not restored to stamped content"
        )


class TestCheckpointEmptyWhenClean:
    """Checkpoint mode shows nothing when all files match stamps."""

    def test_checkpoint_shows_dirty_settings(self, emulator_harness: AppHarness) -> None:
        """The emulator starts with settings.yml and config.txt dirty (changed
        after factory snapshots) so checkpoint mode shows them."""
        harness = emulator_harness
        harness.select("Reset to Checkpoint")
        harness.inject()

        harness.select("Config")
        harness.inject()
        rows = harness.row_labels()
        assert "settings.yml *" in rows, f"expected settings.yml * in {rows}"
        assert "default_config.yml *" in rows, f"expected default_config.yml * in {rows}"

    def test_checkpoint_pedalboards_shows_stamped_dirty(self, emulator_harness: AppHarness) -> None:
        """AmpBud is stamped and modified, so it appears in checkpoint mode."""
        harness = emulator_harness
        harness.select("Reset to Checkpoint")
        harness.inject()

        harness.select("Pedalboards")
        harness.inject()
        rows = harness.row_labels()
        assert "AmpBud.pedalboard" in rows, f"expected AmpBud.pedalboard in {rows}"
        # Beths is stamped but not dirty — should not appear.
        assert "Beths.pedalboard" not in rows
        # Carbon-Copy and factory-defaults are unstamped — should not appear.
        assert "Carbon-Copy.pedalboard" not in rows
        assert "factory-defaults.pedalboard" not in rows