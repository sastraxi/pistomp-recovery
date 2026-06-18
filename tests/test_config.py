"""Tests for the config recovery facet (copy + hash model)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pistomp_recovery import config


@pytest.fixture
def config_facet(tmp_path: Path) -> config.FileFacet:
    """Return an isolated config FileFacet backed by temp directories."""
    source = tmp_path / "config"
    repo = tmp_path / "config.git"
    source.mkdir()
    repo.mkdir()
    return config.FileFacet(
        name="config",
        repo_dir=repo,
        files=("default_config.yml", "settings.yml"),
        source_resolver=lambda filename: source / filename,
        display_name_resolver=lambda filename: filename,
    )


class TestInitConfig:
    def test_copies_existing_files_as_factory_state(
        self, config_facet: config.FileFacet
    ) -> None:
        source = config_facet._source_path("default_config.yml").parent
        (source / "default_config.yml").write_text("factory default")
        (source / "settings.yml").write_text("factory settings")

        config_facet.init()

        repo = config_facet.repo_dir
        assert (repo / "default_config.yml").read_text() == "factory default"
        assert (repo / "settings.yml").read_text() == "factory settings"
        assert git_branch_exists(repo, "factory")

    def test_factory_branch_created_only_once(
        self, config_facet: config.FileFacet
    ) -> None:
        source = config_facet._source_path("default_config.yml").parent
        (source / "default_config.yml").write_text("v1")

        config_facet.init()
        (source / "default_config.yml").write_text("v2")
        config_facet.init()

        # Second init should not re-snapshot; factory stays at v1.
        assert (config_facet.repo_dir / "default_config.yml").read_text() == "v1"


class TestDirtyDetection:
    def test_clean_when_files_match(self, config_facet: config.FileFacet) -> None:
        source = config_facet._source_path("default_config.yml").parent
        (source / "default_config.yml").write_text("same")
        config_facet.init()

        assert not config_facet.is_dirty()

    def test_dirty_when_live_file_changes(self, config_facet: config.FileFacet) -> None:
        source = config_facet._source_path("default_config.yml").parent
        (source / "default_config.yml").write_text("same")
        config_facet.init()
        (source / "default_config.yml").write_text("changed")

        assert config_facet.is_dirty()

    def test_dirty_when_live_file_deleted(self, config_facet: config.FileFacet) -> None:
        source = config_facet._source_path("settings.yml").parent
        (source / "settings.yml").write_text("exists")
        config_facet.init()
        (source / "settings.yml").unlink()

        assert config_facet.is_dirty()


class TestStampAndRollback:
    def test_stamp_captures_current_state(
        self, config_facet: config.FileFacet
    ) -> None:
        source = config_facet._source_path("default_config.yml").parent
        (source / "default_config.yml").write_text("v1")
        config_facet.init()
        (source / "default_config.yml").write_text("v2")

        tag = config_facet.stamp()

        assert tag is not None
        assert len(tag) == 40  # commit hash
        assert (config_facet.repo_dir / "default_config.yml").read_text() == "v2"

    def test_rollback_to_factory_restores_deleted_file(
        self, config_facet: config.FileFacet
    ) -> None:
        source = config_facet._source_path("settings.yml").parent
        (source / "settings.yml").write_text("factory")
        config_facet.init()
        (source / "settings.yml").unlink()

        config_facet.rollback("settings.yml", "factory")

        assert (source / "settings.yml").read_text() == "factory"

    def test_rollback_to_factory_deletes_file_not_present_at_factory(
        self, config_facet: config.FileFacet
    ) -> None:
        source = config_facet._source_path("settings.yml").parent
        (source / "default_config.yml").write_text("factory")
        # settings.yml does not exist at factory time.
        config_facet.init()
        (source / "settings.yml").write_text("created later")

        config_facet.rollback("settings.yml", "factory")

        assert not (source / "settings.yml").exists()


def git_branch_exists(repo: Path, branch: str) -> bool:
    from pistomp_recovery import git_util

    return git_util.branch_exists(repo, branch)
