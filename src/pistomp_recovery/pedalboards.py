from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from pistomp_recovery import git_util
from pistomp_recovery.constants import PEDALBOARDS_DIR
from pistomp_recovery.items import Action, Item
from pistomp_recovery.util import human_time

logger = logging.getLogger(__name__)


def _parse_stamp_time(tag: str) -> datetime | None:
    parts: list[str] = tag.rsplit("/", 1)
    if len(parts) < 2:
        return None
    ts_str: str = parts[-1]
    try:
        return datetime.strptime(ts_str, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _dir_mtime(path: Path) -> datetime:
    try:
        from os import stat

        return datetime.fromtimestamp(stat(path).st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.min.replace(tzinfo=timezone.utc)


def init_pedalboards(path: Path = Path(PEDALBOARDS_DIR)) -> None:
    """Ensure pedalboards repo exists with factory and device branches."""
    path.mkdir(parents=True, exist_ok=True)
    if not git_util.is_repo(path):
        git_util.init_repo(path)
        git_util.add_and_commit(path, "initial pedalboards state")
        git_util.create_factory_branch(path)
    git_util.git("checkout", git_util.DEVICE_BRANCH, cwd=path, check=False)


def list_pedalboard_items(path: Path = Path(PEDALBOARDS_DIR)) -> list[Item]:
    """Return Item list for each .pedalboard directory."""
    init_pedalboards(path)
    stamped_items: list[Item] = []
    unstamped_items: list[Item] = []
    if not path.is_dir():
        return []

    for entry in sorted(path.iterdir()):
        if not entry.is_dir() or not entry.name.endswith(".pedalboard"):
            continue
        is_dirty: bool = bool(
            git_util.git(
                "status", "--porcelain", "--", str(entry),
                cwd=path, check=False,
            ).strip()
        )
        stamp_tag: str | None = git_util.last_stamp(
            path, f"pedalboard/{entry.name}"
        )
        stamp_time: datetime | None = _parse_stamp_time(stamp_tag) if stamp_tag else None

        if stamp_time:
            right: str = human_time(stamp_time)
        elif not is_dirty:
            right = "factory"
        else:
            right = "?"

        label: str = entry.name
        dirty: bool = is_dirty
        actions: list[Action] = [
            Action(
                "Rollback to stamp",
                lambda n=entry.name: rollback_pedalboard(n, "stamp"),
                confirm=f"Rollback {entry.name}\nto last stamp?",
            ),
            Action(
                "Rollback to factory",
                lambda n=entry.name: rollback_pedalboard(n, "factory"),
                confirm=f"Rollback {entry.name}\nto factory?",
            ),
        ]
        if not stamp_time:
            actions = [a for a in actions if a.label != "Rollback to stamp"]

        item = Item(
            name=entry.name,
            label=label,
            dirty=dirty,
            right=right,
            actions=actions,
        )
        if stamp_time is not None:
            stamped_items.append(item)
        else:
            unstamped_items.append(item)

    stamped_items.sort(
        key=lambda i: _parse_stamp_time(
            git_util.last_stamp(path, f"pedalboard/{i.name}") or ""
        )
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    unstamped_items.sort(key=lambda i: _dir_mtime(path / i.name), reverse=True)
    result: list[Item] = []
    result.extend(stamped_items)
    result.extend(unstamped_items)
    return result


def stamp_pedalboard(name: str, path: Path = Path(PEDALBOARDS_DIR)) -> str:
    """Create a git tag for this pedalboard's current state."""
    init_pedalboards(path)
    item_path: Path = path / name
    git_util.git("add", str(item_path), cwd=path, check=False)
    tag_name: str = git_util.stamp(path, f"pedalboard/{name}")
    return tag_name


def stamp_pedalboard_repo(path: Path = Path(PEDALBOARDS_DIR)) -> str:
    """Create a holistic git tag for the entire pedalboards repo state."""
    init_pedalboards(path)
    git_util.add_and_commit(path, "stamp pedalboards")
    tag_name: str = git_util.stamp(path, "pedalboards")
    return tag_name


def rollback_pedalboard(
    name: str, target: str, path: Path = Path(PEDALBOARDS_DIR)
) -> None:
    """Restore pedalboard to last stamp or factory state."""
    init_pedalboards(path)
    item_path: Path = path / name
    if target == "factory":
        git_util.git(
            "checkout", git_util.FACTORY_BRANCH, "--", str(item_path), cwd=path
        )
    else:
        tag: str | None = git_util.last_stamp(path, f"pedalboard/{name}")
        if tag:
            git_util.git("checkout", tag, "--", str(item_path), cwd=path)
    git_util.add_and_commit(path, f"rollback {name}")


def factory_reset_pedalboard(name: str, path: Path = Path(PEDALBOARDS_DIR)) -> None:
    """Same as rollback to factory — kept as explicit API for clarity."""
    rollback_pedalboard(name, "factory", path)
