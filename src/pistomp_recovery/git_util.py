from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pistomp_recovery.constants import DEVICE_BRANCH, FACTORY_BRANCH

logger = logging.getLogger(__name__)


class GitError(Exception):
    pass


def git(*args: str, cwd: str | Path, check: bool = True) -> str:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git"] + list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def is_repo(path: Path) -> bool:
    return (path / ".git").is_dir() or (path / "HEAD").exists()


def remote_head(path: Path) -> str | None:
    """Return the hash of HEAD on origin, or None if unreachable/no remote."""
    remote: str = git("remote", "get-url", "origin", cwd=path, check=False)
    if not remote:
        return None
    result: str = git("ls-remote", "origin", "HEAD", cwd=path, check=False)
    if not result:
        return None
    return result.split()[0]


def fetch_origin(path: Path) -> None:
    """Fetch the default branch from origin with depth 1."""
    for branch in ("master", "main"):
        code: int = subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", branch],
            cwd=str(path),
            capture_output=True,
            text=True,
        ).returncode
        if code == 0:
            return
    raise GitError("git fetch --depth 1 origin: no default branch found (tried master, main)")


def remote_changed_dirs(path: Path, suffix: str, remote_ref: str = "FETCH_HEAD") -> set[str]:
    """Return set of top-level directory names ending in *suffix*
    with changes between HEAD and remote."""
    output: str = git("diff", "--name-only", "HEAD", remote_ref, cwd=path, check=False)
    if not output:
        return set()
    result: set[str] = set()
    for line in output.splitlines():
        top: str = line.split("/", 1)[0]
        if top.endswith(suffix):
            result.add(top)
    return result


def init_repo(path: Path) -> None:
    if not (path / ".git").is_dir():
        path.mkdir(parents=True, exist_ok=True)
        git("init", "--initial-branch", DEVICE_BRANCH, cwd=path)
        git("config", "user.email", "recovery@pistomp.local", cwd=path)
        git("config", "user.name", "pistomp-recovery", cwd=path)


def add_and_commit(path: Path, message: str) -> str | None:
    """Commit all changes. Returns the commit hash, or None if nothing changed."""
    git("add", "-A", cwd=path)
    status: str = git("status", "--porcelain", cwd=path, check=False)
    if not status:
        logger.debug("No changes to commit in %s", path)
        return None
    git(
        "-c",
        "user.email=recovery@pistomp.local",
        "-c",
        "user.name=pistomp-recovery",
        "commit",
        "-m",
        message,
        cwd=path,
    )
    return git("rev-parse", "HEAD", cwd=path)


def rollback(path: Path, branch: str = FACTORY_BRANCH, ref: str | None = None) -> None:
    target_ref: str = ref if ref else branch
    git("checkout", DEVICE_BRANCH, cwd=path)
    git("checkout", target_ref, "--", ".", cwd=path)
    add_and_commit(path, f"rollback to {target_ref}")


def _first_commit_for_path(path: Path, rel_path: str) -> str | None:
    """Return the hash of the first commit that touched *rel_path*."""
    result: str = git("log", "--reverse", "--format=%H", "--", rel_path, cwd=path, check=False)
    return result.splitlines()[0] if result else None


def rollback_path(path: Path, rel_path: str, ref: str | None = None) -> None:
    """Restore a single path from factory branch (or a specific ref)."""
    source_ref: str
    if ref:
        source_ref = ref
    else:
        first: str | None = _first_commit_for_path(path, rel_path)
        if first is None:
            raise GitError(f"no factory state found for {rel_path} (path was never committed)")
        source_ref = first
    git("rm", "-rq", "--", rel_path, cwd=path, check=False)
    git("checkout", source_ref, "--", rel_path, cwd=path)
    git("clean", "-fd", "--", rel_path, cwd=path)
    add_and_commit(path, f"rollback {rel_path} to {source_ref}")


def create_factory_branch(path: Path) -> None:
    if DEVICE_BRANCH == "main" or DEVICE_BRANCH == "master":
        git("checkout", "-b", FACTORY_BRANCH, cwd=path)
    else:
        current: str = git("branch", "--show-current", cwd=path, check=False)
        if current != FACTORY_BRANCH:
            git("branch", FACTORY_BRANCH, cwd=path)
    git("checkout", DEVICE_BRANCH, cwd=path)


def branch_exists(path: Path, branch: str) -> bool:
    """Return True if the named branch exists in the repo."""
    result: str = git("branch", "--list", branch, cwd=path, check=False)
    return bool(result.strip())


def matches_ref(path: Path, rel_path: str, ref: str) -> bool:
    """Return True if HEAD's content for *rel_path* equals *ref*'s content.

    ``git diff --quiet`` exits 0 when there are no differences.
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "diff", "--quiet", ref, "HEAD", "--", rel_path],
        cwd=str(path),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_at_factory(path: Path, rel_path: str) -> bool:
    """Return True if HEAD's content for *rel_path* matches its first commit.

    This mirrors ``rollback_path``'s factory ref: the first commit that
    touched the path, NOT the ``factory`` branch (which may not exist or may
    point elsewhere). Returns False if the path was never committed.
    """
    first: str | None = _first_commit_for_path(path, rel_path)
    if first is None:
        return False
    return matches_ref(path, rel_path, first)


def last_commit_time(path: Path) -> datetime | None:
    """Return the commit time of HEAD, or None if no commits exist."""
    result: str = git("log", "-1", "--format=%ct", cwd=path, check=False)
    if not result:
        return None
    try:
        return datetime.fromtimestamp(int(result), tz=timezone.utc)
    except (ValueError, OSError):
        return None


def last_commit_time_for_path(path: Path, rel_path: str) -> datetime | None:
    """Return the commit time of the last commit that touched ``rel_path``."""
    result: str = git("log", "-1", "--format=%ct", "--", rel_path, cwd=path, check=False)
    if not result:
        return None
    try:
        return datetime.fromtimestamp(int(result), tz=timezone.utc)
    except (ValueError, OSError):
        return None


def last_commit_for_path(path: Path, rel_path: str) -> str | None:
    """Return the commit hash of the last commit that touched ``rel_path``."""
    result: str = git("log", "-1", "--format=%H", "--", rel_path, cwd=path, check=False)
    if not result:
        return None
    return result
