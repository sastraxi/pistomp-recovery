# pyright: reportPrivateUsage=false
"""Saga tests — end-to-end domain actions using real emulator backends.

These test the full action pipeline: navigate to a domain item → confirm →
action fires → screen refreshes → file state changes.  They use
``EmulatorDataBackend`` (real stubs) so the facet actions actually modify
live files and stamps.
"""

from __future__ import annotations

from collections.abc import Iterator

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
from pistomp_recovery.service import BootMode, CrashInfo
from pistomp_recovery.ui.widgets.misc import InputEvent
from tests.conftest import AppHarness


@pytest.fixture
def emulator_harness() -> Iterator[AppHarness]:
    display = PygameDisplayBackend()
    encoder = FakeEncoderInput()
    inp = FakeInputBackend(encoder)
    data = EmulatorDataBackend()
    services = EmulatorServiceBackend(BootMode.USER_RECOVERY)

    app = RecoveryAppCore(
        AppBackends(display=display, input=inp, data=data, services=services),
        CrashInfo(
            boot_mode=BootMode.USER_RECOVERY,
            failed_service=None,
            crash_log="",
            service_states={},
        ),
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


class TestSystemDomainPackages:
    """System domain now maps to the packages facet."""

    def test_updates_shows_package_updates_under_system(
        self, emulator_harness: AppHarness
    ) -> None:
        """Updates → System shows package updates (previously orphaned)."""
        harness = emulator_harness

        harness.select("Updates")
        harness.drain()
        harness.select("System")
        harness.inject()
        rows = harness.row_labels()
        assert any("jack2-pistomp" in r for r in rows), (
            f"jack2-pistomp not in System updates: {rows}"
        )
        assert any("mod-ui" in r for r in rows), (
            f"mod-ui not in System updates: {rows}"
        )

    def test_updates_picker_shows_only_system(self, emulator_harness: AppHarness) -> None:
        """Updates picker only shows System; pedalboards/plugins/config are excluded."""
        harness = emulator_harness

        harness.select("Updates")
        harness.drain()
        labels = harness.row_labels()
        assert labels == ["System"], f"unexpected Updates picker labels: {labels}"

    def test_factory_reset_system_shows_package_items(
        self, emulator_harness: AppHarness
    ) -> None:
        """Factory Reset → System shows package rollback items."""
        harness = emulator_harness

        harness.select("Factory Reset")
        harness.inject()
        harness.select("System")
        harness.inject()
        rows = harness.row_labels()
        assert any("jack2-pistomp" in r for r in rows), (
            f"package items not in System factory reset: {rows}"
        )

    def test_factory_reset_boot_file_action_targets_correct_facet(
        self, emulator_harness: AppHarness
    ) -> None:
        """Factory-resetting a boot file from Config restores that file,
        not any config-facet file."""
        harness = emulator_harness
        data = harness.app._backends.data
        assert isinstance(data, EmulatorDataBackend)

        config_txt = data._system_dir / "config.txt"
        settings_yml = data._config_dir / "settings.yml"

        harness.select("Factory Reset")
        harness.inject()
        harness.select("Config")
        harness.inject()

        harness.select("config.txt")
        harness.inject()
        harness.inject(InputEvent.RIGHT, InputEvent.CLICK)  # Yes
        harness.inject(InputEvent.CLICK)                     # dismiss done
        harness.inject()

        assert config_txt.read_text() == "# factory config.txt\n", (
            f"config.txt not restored: {config_txt.read_text()!r}"
        )
        # settings.yml must NOT be affected — action was bound to the boot facet
        assert settings_yml.read_text() == "# changed settings\n", (
            "settings.yml was incorrectly modified by a boot-facet rollback"
        )


class TestCheckpointEmptyWhenClean:
    """Checkpoint mode shows nothing when all files match stamps."""

    def test_checkpoint_shows_dirty_settings(self, emulator_harness: AppHarness) -> None:
        """The emulator starts with settings.yml and config.txt dirty (changed
        after factory snapshots) so checkpoint mode shows them.
        Config domain now includes both config and boot facet files."""
        harness = emulator_harness
        harness.select("Reset to Checkpoint")
        harness.inject()

        harness.select("Config")
        harness.inject()
        rows = harness.row_labels()
        assert "settings.yml *" in rows, f"expected settings.yml * in {rows}"
        assert "default_config.yml *" in rows, f"expected default_config.yml * in {rows}"
        # config.txt is a boot-facet file now shown under Config
        assert "config.txt *" in rows, f"expected config.txt * in {rows}"

    def test_checkpoint_boot_file_in_config_domain(self, emulator_harness: AppHarness) -> None:
        """Boot-facet files (config.txt) now appear under Config domain."""
        harness = emulator_harness
        data = harness.app._backends.data
        assert isinstance(data, EmulatorDataBackend)

        # config.txt is dirty in the emulator (changed after stamp)
        config_txt = data._system_dir / "config.txt"
        assert config_txt.read_text() == "# changed config.txt\n"

        harness.select("Factory Reset")
        harness.inject()
        harness.select("Config")
        harness.inject()
        rows = harness.row_labels()
        assert any("config.txt" in r for r in rows), f"config.txt not under Config: {rows}"

        # System domain maps to packages only — verify via backend directly
        system_items = data.domain_items("factory", "system")
        assert not any(it.name == "config.txt" for it in system_items), (
            "config.txt leaked into System domain"
        )

    def test_checkpoint_pedalboards_shows_stamped_dirty(
        self, emulator_harness: AppHarness
    ) -> None:
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
