"""Tests for the system recovery facet (copy + hash model)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pistomp_recovery import system


@pytest.fixture
def system_facet(tmp_path: Path) -> system.FileFacet:
    """Return an isolated system FileFacet backed by temp directories."""
    source = tmp_path / "system"
    repo = tmp_path / "system.git"
    source.mkdir()
    repo.mkdir()

    # Map the absolute system paths used by the module into our temp tree.
    boot = source / "boot"
    etc = source / "etc"
    var = source / "var" / "lib" / "alsa"
    boot.mkdir()
    etc.mkdir()
    var.mkdir(parents=True)

    test_files = {
        "config.txt": str(boot / "config.txt"),
        "cmdline.txt": str(boot / "cmdline.txt"),
        "pistomp.conf": str(boot / "pistomp.conf"),
        "jackdrc": str(etc / "jackdrc"),
        "asound.state": str(var / "asound.state"),
    }

    return system.FileFacet(
        name="system",
        repo_dir=repo,
        files=tuple(test_files.keys()),
        source_resolver=lambda name: Path(test_files[name]),
        display_name_resolver=lambda name: name,
    )


class TestInitSystem:
    def test_copies_existing_files_as_factory_state(
        self, system_facet: system.FileFacet
    ) -> None:
        for filename in system_facet.files:
            Path(system_facet._source_path(filename)).write_text(
                f"factory {filename}"
            )

        system_facet.init()

        for filename in system_facet.files:
            assert (system_facet.repo_dir / filename).read_text() == f"factory {filename}"
        assert git_branch_exists(system_facet.repo_dir, "factory")

    def test_factory_branch_created_only_once(
        self, system_facet: system.FileFacet
    ) -> None:
        first = system_facet.files[0]
        Path(system_facet._source_path(first)).write_text("v1")

        system_facet.init()
        Path(system_facet._source_path(first)).write_text("v2")
        system_facet.init()

        assert (system_facet.repo_dir / first).read_text() == "v1"


class TestDirtyDetection:
    def test_clean_when_files_match(self, system_facet: system.FileFacet) -> None:
        for filename in system_facet.files:
            Path(system_facet._source_path(filename)).write_text("same")
        system_facet.init()

        assert not system_facet.is_dirty()

    def test_dirty_when_live_file_changes(
        self, system_facet: system.FileFacet
    ) -> None:
        first = system_facet.files[0]
        Path(system_facet._source_path(first)).write_text("same")
        system_facet.init()
        Path(system_facet._source_path(first)).write_text("changed")

        assert system_facet.is_dirty()


class TestStampAndRollback:
    def test_stamp_captures_current_state(
        self, system_facet: system.FileFacet
    ) -> None:
        first = system_facet.files[0]
        Path(system_facet._source_path(first)).write_text("v1")
        system_facet.init()
        Path(system_facet._source_path(first)).write_text("v2")

        tag = system_facet.stamp()

        assert tag is not None
        assert len(tag) == 40  # commit hash
        assert (system_facet.repo_dir / first).read_text() == "v2"

    def test_rollback_to_factory_restores_changed_file(
        self, system_facet: system.FileFacet
    ) -> None:
        first = system_facet.files[0]
        Path(system_facet._source_path(first)).write_text("factory")
        system_facet.init()
        Path(system_facet._source_path(first)).write_text("changed")

        system_facet.rollback(first, "factory")

        assert Path(system_facet._source_path(first)).read_text() == "factory"


def git_branch_exists(repo: Path, branch: str) -> bool:
    from pistomp_recovery import git_util

    return git_util.branch_exists(repo, branch)
