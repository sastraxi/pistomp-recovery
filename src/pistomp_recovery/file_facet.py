from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from pistomp_recovery import git_util
from pistomp_recovery.facet import RollbackTarget
from pistomp_recovery.items import Action, Item
from pistomp_recovery.util import human_time

logger = logging.getLogger(__name__)


def _file_equal(a: Path, b: Path) -> bool:
    """Return True if both paths exist with identical content, or both are missing."""
    if a.exists() != b.exists():
        return False
    if not a.exists():
        return True
    return a.read_bytes() == b.read_bytes()


class FileFacet:
    """Recovery facet for a set of files tracked via copy + commit.

    Live files remain at their original paths. On init and stamp, the current
    file contents are copied into ``repo_dir`` and committed. Rollback checks
    out a ref in the repo and copies files back to their live paths.
    """

    name: str

    def __init__(
        self,
        *,
        name: str,
        repo_dir: Path,
        files: tuple[str, ...],
        source_resolver: Callable[[str], Path],
        display_name_resolver: Callable[[str], str],
    ) -> None:
        self.name = name
        self.repo_dir = repo_dir
        self.files = files
        self._source_path = source_resolver
        self._display_name = display_name_resolver

    def _repo_path(self, filename: str) -> Path:
        return self.repo_dir / filename

    def _copy_to_repo(self, filename: str) -> None:
        """Copy the live file into the repo, or remove the repo copy if the live file is gone."""
        src = self._source_path(filename)
        dst = self._repo_path(filename)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()

    def _copy_from_repo(self, filename: str) -> None:
        """Copy a repo file back to the live path.

        If the repo copy is gone, delete the live file instead.
        """
        src = self._repo_path(filename)
        dst = self._source_path(filename)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()

    def snapshot(self) -> None:
        for filename in self.files:
            self._copy_to_repo(filename)

    def is_dirty(self) -> bool:
        for filename in self.files:
            if not _file_equal(self._source_path(filename), self._repo_path(filename)):
                return True
        return False

    def init_repo(self) -> None:
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        if not git_util.is_repo(self.repo_dir):
            git_util.init_repo(self.repo_dir)

        if not git_util.branch_exists(self.repo_dir, git_util.FACTORY_BRANCH):
            self.snapshot()
            git_util.add_and_commit(self.repo_dir, f"initial {self.name} state")
            git_util.create_factory_branch(self.repo_dir)

        git_util.git("checkout", git_util.DEVICE_BRANCH, cwd=self.repo_dir, check=False)

    # Facet protocol aliases
    init = init_repo

    def rollback(self, name: str, target: RollbackTarget) -> None:
        self.rollback_file(name, target)

    def stamp_time(self) -> datetime | None:
        return git_util.last_commit_time(self.repo_dir)

    def stamp(self) -> str | None:
        self.init_repo()
        self.snapshot()
        return git_util.add_and_commit(self.repo_dir, f"{self.name} stamp")

    def _exists_in_ref(self, filename: str, ref: str) -> bool:
        """Return True if ``filename`` is tracked in ``ref``."""
        result: str = git_util.git(
            "ls-tree", ref, "--", filename, cwd=self.repo_dir, check=False
        )
        return bool(result.strip())

    def _delete_from_repo(self, filename: str) -> None:
        repo_file = self._repo_path(filename)
        if repo_file.exists():
            repo_file.unlink()

    def rollback_file(self, filename: str, target: RollbackTarget) -> None:
        """Rollback a single file to stamp or factory."""
        self.init_repo()
        ref = git_util.FACTORY_BRANCH if target == "factory" else "HEAD"
        if self._exists_in_ref(filename, ref):
            git_util.git("checkout", ref, "--", filename, cwd=self.repo_dir)
        else:
            self._delete_from_repo(filename)
        self._copy_from_repo(filename)
        git_util.add_and_commit(self.repo_dir, f"rollback {filename}")

    def rollback_all(self, target: RollbackTarget) -> None:
        """Rollback all files to stamp or factory."""
        self.init_repo()
        ref = git_util.FACTORY_BRANCH if target == "factory" else "HEAD"
        git_util.git("checkout", ref, "--", ".", cwd=self.repo_dir)
        for filename in self.files:
            if not self._exists_in_ref(filename, ref):
                self._delete_from_repo(filename)
            self._copy_from_repo(filename)
        git_util.add_and_commit(self.repo_dir, f"rollback to {ref}")

    def list_items(self) -> list[Item]:
        self.init_repo()
        dirty = self.is_dirty()
        stamp_time = self.stamp_time()

        items: list[Item] = []
        for filename in self.files:
            src = self._source_path(filename)
            repo_copy = self._repo_path(filename)
            if not src.exists() and not repo_copy.exists():
                continue

            display_name = self._display_name(filename)
            actions: list[Action] = []
            if stamp_time:
                actions.append(
                    Action(
                        "Rollback to stamp",
                        lambda f=filename: self.rollback_file(f, "stamp"),
                        confirm=f"Rollback {display_name}\nto last stamp?",
                    )
                )
            actions.append(
                Action(
                    "Rollback to factory",
                    lambda f=filename: self.rollback_file(f, "factory"),
                    confirm=f"Reset {display_name}\nto factory?",
                )
            )

            items.append(
                Item(
                    name=display_name,
                    label=display_name + (" *" if dirty else ""),
                    dirty=dirty,
                    right=human_time(stamp_time) if stamp_time else "factory",
                    actions=actions,
                )
            )
        return items
