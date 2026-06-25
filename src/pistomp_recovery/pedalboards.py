from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from pistomp_recovery import git_util
from pistomp_recovery.constants import PEDALBOARDS_DIR
from pistomp_recovery.facet import RollbackTarget
from pistomp_recovery.items import Action, Item
from pistomp_recovery.util import human_time

logger = logging.getLogger(__name__)


def _dir_mtime(path: Path) -> datetime:
    try:
        from os import stat

        return datetime.fromtimestamp(stat(path).st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.min.replace(tzinfo=timezone.utc)


class PedalboardFacet:
    """Recovery facet for the pedalboards git repo."""

    name = "pedalboards"
    default_path: Path = Path(PEDALBOARDS_DIR)

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path

    def init(self, path: Path | None = None) -> None:
        target = path or self.path
        target.mkdir(parents=True, exist_ok=True)
        if not git_util.is_repo(target):
            git_util.init_repo(target)
            git_util.add_and_commit(target, "initial pedalboards state")
            git_util.create_factory_branch(target)
        git_util.git("checkout", git_util.DEVICE_BRANCH, cwd=target, check=False)

    def list_items(self, path: Path | None = None) -> list[Item]:
        target = path or self.path
        self.init(target)
        stamped_items: list[Item] = []
        unstamped_items: list[Item] = []
        if not target.is_dir():
            return []

        for entry in sorted(target.iterdir()):
            if not entry.is_dir() or not entry.name.endswith(".pedalboard"):
                continue
            is_dirty: bool = bool(
                git_util.git(
                    "status",
                    "--porcelain",
                    "--",
                    str(entry),
                    cwd=target,
                    check=False,
                ).strip()
            )
            stamp_time: datetime | None = git_util.last_commit_time_for_path(target, entry.name)
            stamp_hash: str | None = git_util.last_commit_for_path(target, entry.name)
            is_factory: bool = git_util.is_at_factory(target, entry.name)

            if is_dirty:
                right: str = "?"
            elif is_factory:
                right = "factory"
            elif stamp_time:
                right = human_time(stamp_time)
            else:
                right = "?"

            label: str = entry.name
            dirty: bool = is_dirty
            actions: list[Action] = [
                Action(
                    "Rollback to stamp",
                    lambda n=entry.name: self.rollback(n, "stamp"),
                    confirm=f"Rollback {entry.name}\nto last stamp?",
                ),
                Action(
                    "Rollback to factory",
                    lambda n=entry.name: self.rollback(n, "factory"),
                    confirm=f"Rollback {entry.name}\nto factory?",
                ),
            ]
            if not stamp_hash:
                actions = [a for a in actions if a.label != "Rollback to stamp"]

            item = Item(
                name=entry.name,
                label=label,
                dirty=dirty,
                right=right,
                actions=actions,
            )
            if stamp_hash is not None and not is_factory:
                stamped_items.append(item)
            else:
                unstamped_items.append(item)

        stamped_items.sort(key=lambda i: _dir_mtime(target / i.name), reverse=True)
        unstamped_items.sort(key=lambda i: _dir_mtime(target / i.name), reverse=True)
        factory_items: list[Item] = [i for i in unstamped_items if not i.dirty]
        unstamped_items = [i for i in unstamped_items if i.dirty]
        factory_items.sort(key=lambda i: i.name)
        result: list[Item] = []
        result.extend(unstamped_items)
        result.extend(stamped_items)
        result.extend(factory_items)
        return result

    def stamp(self, path: Path | None = None) -> str | None:
        target = path or self.path
        self.init(target)
        return git_util.add_and_commit(target, "stamp pedalboards")

    def stamp_item(self, name: str, path: Path | None = None) -> str | None:
        """Commit a single pedalboard's current state."""
        target = path or self.path
        self.init(target)
        item_path: Path = target / name
        git_util.git("add", str(item_path), cwd=target, check=False)
        return git_util.add_and_commit(target, f"stamp {name}")

    def rollback(self, name: str, target: RollbackTarget, path: Path | None = None) -> None:
        """Restore pedalboard to last stamp or factory state."""
        repo = path or self.path
        self.init(repo)
        if target == "factory":
            git_util.rollback_path(repo, name)
        else:
            ref = git_util.last_commit_for_path(repo, name)
            if ref:
                git_util.rollback_path(repo, name, ref=ref)

    def remote_updates(self) -> list[Item]:
        return []


def make_pedalboard_facet(path: Path | None = None) -> PedalboardFacet:
    """Return a fresh pedalboard facet for registration by an entry point."""
    return PedalboardFacet(path)
