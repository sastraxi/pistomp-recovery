from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pistomp_recovery.constants import (
    FACTORY_PACKAGES_FILE,
    PACKAGES_STAMP_FILE,
    PISTOMP_PACKAGES,
)
from pistomp_recovery.items import Action, Item
from pistomp_recovery.packages import installer
from pistomp_recovery.util import human_time

logger = logging.getLogger(__name__)


def _collect_versions() -> dict[str, str]:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["pacman", "-Q"],
        capture_output=True,
        text=True,
    )
    all_packages: dict[str, str] = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts: list[str] = line.split(None, 1)
        if len(parts) == 2:
            all_packages[parts[0]] = parts[1]
    tracked: dict[str, str] = {}
    for pkg in PISTOMP_PACKAGES:
        tracked[pkg] = all_packages.get(pkg, "not-installed")
    return tracked


def _read_stamp_file() -> dict[str, str]:
    path: Path = Path(PACKAGES_STAMP_FILE)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read packages stamp file")
        return {}


def _read_factory_file() -> dict[str, str]:
    path: Path = Path(FACTORY_PACKAGES_FILE)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read factory packages file")
        return {}


def _write_stamp_file() -> None:
    versions: dict[str, str] = _collect_versions()
    path: Path = Path(PACKAGES_STAMP_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(versions, indent=2, sort_keys=True))


def stamp_packages() -> None:
    """Write current pacman versions to stamp file."""
    _write_stamp_file()


def get_available_updates() -> list[tuple[str, str, str]]:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["pacman", "-Qu", *PISTOMP_PACKAGES],
        capture_output=True,
        text=True,
    )
    updates: list[tuple[str, str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts: list[str] = line.split()
        if len(parts) >= 3:
            updates.append((parts[0], parts[1], parts[2]))
        elif len(parts) == 2:
            updates.append((parts[0], "unknown", parts[1]))
    return updates


def list_package_items() -> list[Item]:
    """Return Item list for each tracked package."""
    installed: dict[str, str] = _collect_versions()
    stamped: dict[str, str] = _read_stamp_file()
    factory: dict[str, str] = _read_factory_file()
    available: dict[str, str] = {}
    for pkg_name, _old_v, new_v in get_available_updates():
        available[pkg_name] = new_v

    # Monolithic stamp time from stamp file mtime
    stamp_time: datetime | None = None
    stamp_path: Path = Path(PACKAGES_STAMP_FILE)
    if stamp_path.exists():
        try:
            stamp_time = datetime.fromtimestamp(
                stamp_path.stat().st_mtime, tz=timezone.utc
            )
        except OSError:
            pass

    items: list[Item] = []
    for pkg in PISTOMP_PACKAGES:
        inst: str = installed.get(pkg, "not-installed")
        stamp: str = stamped.get(pkg, "not-installed")
        fact: str = factory.get(pkg, "not-installed")
        avail: str | None = available.get(pkg)
        is_dirty: bool = inst != stamp

        if is_dirty and stamp_time:
            right = human_time(stamp_time)
        elif is_dirty:
            right = "?"
        else:
            right = human_time(stamp_time) if stamp_time else "factory"

        if avail:
            right = f"\u2191{avail}"

        label: str = pkg + (" *" if is_dirty else "")
        actions: list[Action] = []
        if avail:
            actions.append(
                Action(
                    f"Update to {avail}",
                    lambda p=pkg: _install_single(p),
                    confirm=f"Update {pkg}\nto {avail}?",
                )
            )
        if is_dirty and stamp != "not-installed":
            actions.append(
                Action(
                    "Rollback to stamp",
                    lambda p=pkg: rollback_package(p, "stamp"),
                    confirm=f"Rollback {pkg}\nto stamp?",
                )
            )
        if fact != "not-installed":
            actions.append(
                Action(
                    "Rollback to factory",
                    lambda p=pkg: rollback_package(p, "factory"),
                    confirm=f"Rollback {pkg}\nto factory?",
                )
            )
        items.append(
            Item(name=pkg, label=label, dirty=is_dirty, right=right, actions=actions)
        )
    return items


def _install_single(pkg: str) -> None:
    if not installer.download_packages([pkg]):
        logger.error("Download failed for %s", pkg)
        return
    if not installer.install_packages([pkg]):
        logger.error("Install failed for %s", pkg)
        installer.install_from_cache([pkg])
        return
    stamp_packages()


def rollback_package(name: str, target: str) -> None:
    """Rollback package to stamped or factory version via pacman -U."""
    stamped: dict[str, str] = _read_stamp_file()
    factory: dict[str, str] = _read_factory_file()
    version: str | None = None
    if target == "stamp":
        version = stamped.get(name)
    elif target == "factory":
        version = factory.get(name)
    if not version or version == "not-installed":
        logger.warning("No version found for %s in target %s", name, target)
        return
    logger.info("Rolling back %s to %s", name, version)
    subprocess.run(
        ["pacman", "-U", "--noconfirm", f"{name}={version}"],
        check=False,
    )
