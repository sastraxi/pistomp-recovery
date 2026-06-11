from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from pistomp_recovery import git_util
from pistomp_recovery.constants import CONFIG_DIR, RECOVERY_DIR
from pistomp_recovery.items import Action, Item
from pistomp_recovery.util import human_time

logger = logging.getLogger(__name__)

CONFIG_FILES: tuple[str, ...] = (
    "default_config.yml",
    "settings.yml",
)
CONFIG_REPO: Path = Path(RECOVERY_DIR) / "config.git"


def init_config() -> None:
    """Ensure config repo exists with factory and device branches."""
    CONFIG_REPO.mkdir(parents=True, exist_ok=True)
    if not git_util.is_repo(CONFIG_REPO):
        git_util.init_repo(CONFIG_REPO)
    for filename in CONFIG_FILES:
        src: Path = Path(CONFIG_DIR) / filename
        link: Path = CONFIG_REPO / filename
        if src.exists() and not link.exists():
            link.symlink_to(src)
    git_util.add_and_commit(CONFIG_REPO, "initial config state")
    git_util.create_factory_branch(CONFIG_REPO)
    git_util.git("checkout", git_util.DEVICE_BRANCH, cwd=CONFIG_REPO, check=False)


def list_config_items() -> list[Item]:
    """Return Item list for config files. Only dirty-check + rollback actions."""
    init_config()
    is_dirty: bool = bool(
        git_util.git("status", "--porcelain", cwd=CONFIG_REPO, check=False).strip()
    )
    stamp_tag: str | None = git_util.last_stamp(CONFIG_REPO, "config")
    stamp_time: datetime | None = _parse_stamp_time(stamp_tag) if stamp_tag else None

    actions: list[Action] = []
    if stamp_time:
        actions.append(
            Action(
                "Rollback to stamp",
                lambda: rollback_config("stamp"),
                confirm="Rollback config\nto last stamp?",
            )
        )
    actions.append(
        Action(
            "Rollback to factory",
            lambda: rollback_config("factory"),
            confirm="Reset config\nto factory?",
        )
    )

    return [
        Item(
            name="config",
            label="Config" + (" *" if is_dirty else ""),
            dirty=is_dirty,
            right=human_time(stamp_time) if stamp_time else "factory",
            actions=actions,
        ),
    ]


def stamp_config() -> str:
    """Commit and tag current config state."""
    init_config()
    git_util.add_and_commit(CONFIG_REPO, "config stamp")
    return git_util.stamp(CONFIG_REPO, "config")


def rollback_config(target: str) -> None:
    """Rollback config to stamp or factory."""
    init_config()
    if target == "factory":
        git_util.factory_reset(CONFIG_REPO)
    else:
        tag: str | None = git_util.last_stamp(CONFIG_REPO, "config")
        if tag:
            git_util.rollback(CONFIG_REPO, tag)


def _parse_stamp_time(tag: str) -> datetime | None:
    parts: list[str] = tag.rsplit("/", 1)
    if len(parts) < 2:
        return None
    ts_str: str = parts[-1]
    try:
        return datetime.strptime(ts_str, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
