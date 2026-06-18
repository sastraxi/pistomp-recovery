"""Tests for git_util — commit-as-stamp model (no git tags for stamps)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pistomp_recovery import git_util


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git_util.init_repo(path)
    return path


def test_init_repo_creates_device_branch(repo: Path) -> None:
    branch = git_util.git("branch", "--show-current", cwd=repo)
    assert branch == git_util.DEVICE_BRANCH


def test_init_repo_creates_no_factory_branch(repo: Path) -> None:
    assert not git_util.branch_exists(repo, git_util.FACTORY_BRANCH)


def test_add_and_commit_creates_commit(repo: Path) -> None:
    (repo / "test.txt").write_text("hello")
    result = git_util.add_and_commit(repo, "initial")
    assert result is not None  # commit hash
    assert git_util.git("log", "--oneline", cwd=repo) != ""


def test_add_and_commit_returns_none_when_clean(repo: Path) -> None:
    (repo / "test.txt").write_text("hello")
    git_util.add_and_commit(repo, "initial")
    result = git_util.add_and_commit(repo, "no-op")
    assert result is None


def test_add_and_commit_returns_commit_hash(repo: Path) -> None:
    (repo / "test.txt").write_text("hello")
    result = git_util.add_and_commit(repo, "first")
    assert result is not None
    assert len(result) == 40  # SHA-1 hex
    assert git_util.git("rev-parse", "HEAD", cwd=repo) == result


def test_last_commit_time_returns_none_on_empty_repo(repo: Path) -> None:
    assert git_util.last_commit_time(repo) is None


def test_last_commit_time_returns_timestamp(repo: Path) -> None:
    (repo / "test.txt").write_text("hello")
    git_util.add_and_commit(repo, "first")
    t = git_util.last_commit_time(repo)
    assert t is not None
    assert isinstance(t, datetime)
    assert t.tzinfo == timezone.utc


def test_last_commit_time_for_path_returns_none_for_untracked(repo: Path) -> None:
    (repo / "a.txt").write_text("a")
    git_util.add_and_commit(repo, "first")
    assert git_util.last_commit_time_for_path(repo, "b.txt") is None


def test_last_commit_time_for_path_returns_timestamp(repo: Path) -> None:
    (repo / "a.txt").write_text("a")
    git_util.add_and_commit(repo, "first")
    t = git_util.last_commit_time_for_path(repo, "a.txt")
    assert t is not None
    assert isinstance(t, datetime)
    assert t.tzinfo == timezone.utc


def test_last_commit_time_for_path_tracks_per_path(repo: Path) -> None:
    (repo / "a.txt").write_text("a")
    git_util.add_and_commit(repo, "first")
    (repo / "b.txt").write_text("b")
    git_util.add_and_commit(repo, "second")

    hash_a = git_util.last_commit_for_path(repo, "a.txt")
    hash_b = git_util.last_commit_for_path(repo, "b.txt")
    assert hash_a is not None
    assert hash_b is not None
    assert hash_a != hash_b  # different commits touched different paths


def test_last_commit_time_for_path_works_with_subdirs(repo: Path) -> None:
    sub = repo / "subdir"
    sub.mkdir()
    (sub / "file.txt").write_text("content")
    git_util.add_and_commit(repo, "first")
    t = git_util.last_commit_time_for_path(repo, "subdir/file.txt")
    assert t is not None
    assert isinstance(t, datetime)


def test_last_commit_for_path_returns_hash(repo: Path) -> None:
    (repo / "a.txt").write_text("a")
    git_util.add_and_commit(repo, "first")
    (repo / "b.txt").write_text("b")
    git_util.add_and_commit(repo, "second")

    hash_a = git_util.last_commit_for_path(repo, "a.txt")
    hash_b = git_util.last_commit_for_path(repo, "b.txt")
    assert hash_a is not None
    assert hash_b is not None
    assert hash_a != hash_b


def test_last_commit_for_path_returns_none_for_untracked(repo: Path) -> None:
    (repo / "a.txt").write_text("a")
    git_util.add_and_commit(repo, "first")
    assert git_util.last_commit_for_path(repo, "b.txt") is None


def test_factory_branch_starts_at_device_head(repo: Path) -> None:
    (repo / "test.txt").write_text("v1")
    git_util.add_and_commit(repo, "initial")
    git_util.create_factory_branch(repo)
    assert git_util.branch_exists(repo, git_util.FACTORY_BRANCH)
    # factory and device should point to the same commit
    device_head = git_util.git("rev-parse", git_util.DEVICE_BRANCH, cwd=repo)
    factory_head = git_util.git("rev-parse", git_util.FACTORY_BRANCH, cwd=repo)
    assert device_head == factory_head


def test_branch_exists(repo: Path) -> None:
    # branch_exists needs at least one commit — the branch is unborn otherwise
    (repo / "marker").write_text("init")
    git_util.add_and_commit(repo, "initial")
    assert git_util.branch_exists(repo, git_util.DEVICE_BRANCH)
    assert not git_util.branch_exists(repo, "nonexistent")


def test_is_repo(tmp_path: Path) -> None:
    path = tmp_path / "new"
    path.mkdir()
    assert not git_util.is_repo(path)
    git_util.init_repo(path)
    assert git_util.is_repo(path)


def test_rollback_restores_to_factory_state(repo: Path) -> None:
    (repo / "test.txt").write_text("factory")
    git_util.add_and_commit(repo, "initial")
    git_util.create_factory_branch(repo)
    (repo / "test.txt").write_text("device change")
    git_util.add_and_commit(repo, "device change")

    git_util.rollback(repo)

    assert (repo / "test.txt").read_text() == "factory"


def test_rollback_to_specific_commit(repo: Path) -> None:
    (repo / "test.txt").write_text("v1")
    git_util.add_and_commit(repo, "first")
    commit1 = git_util.git("rev-parse", "HEAD", cwd=repo)
    (repo / "test.txt").write_text("v2")
    git_util.add_and_commit(repo, "second")

    git_util.rollback(repo, ref=commit1)

    assert (repo / "test.txt").read_text() == "v1"


def test_rollback_path_restores_file_only(repo: Path) -> None:
    (repo / "keep.txt").write_text("keep")
    (repo / "restore.txt").write_text("original")
    git_util.add_and_commit(repo, "initial")
    git_util.create_factory_branch(repo)
    (repo / "keep.txt").write_text("keep v2")
    (repo / "restore.txt").write_text("modified")

    git_util.rollback_path(repo, "restore.txt")

    assert (repo / "restore.txt").read_text() == "original"
    assert (repo / "keep.txt").read_text() == "keep v2"


def test_rollback_path_to_specific_ref(repo: Path) -> None:
    (repo / "test.txt").write_text("original")
    git_util.add_and_commit(repo, "first")
    commit1 = git_util.git("rev-parse", "HEAD", cwd=repo)
    (repo / "test.txt").write_text("modified")
    git_util.add_and_commit(repo, "second")

    git_util.rollback_path(repo, "test.txt", ref=commit1)

    assert (repo / "test.txt").read_text() == "original"


def test_last_commit_time_for_path_handles_special_chars(repo: Path) -> None:
    name = "My Cool Rig.pedalboard"
    sub = repo / name
    sub.mkdir()
    (sub / "pedalboard.ttl").write_text("content")
    git_util.add_and_commit(repo, "first")
    t = git_util.last_commit_time_for_path(repo, name)
    assert t is not None
    assert isinstance(t, datetime)


def test_last_commit_for_path_handles_special_chars(repo: Path) -> None:
    name = "My Cool Rig.pedalboard"
    sub = repo / name
    sub.mkdir()
    (sub / "pedalboard.ttl").write_text("content")
    git_util.add_and_commit(repo, "first")
    h = git_util.last_commit_for_path(repo, name)
    assert h is not None
    assert len(h) == 40