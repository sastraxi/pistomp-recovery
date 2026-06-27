from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pistomp_recovery.constants import (
    FACTORY_PACKAGES_FILE,
    PACKAGES_STAMP_FILE,
)
from pistomp_recovery.facet import RollbackTarget
from pistomp_recovery.items import Action, Item
from pistomp_recovery.packages.manager import PackageManager, detect_package_manager
from pistomp_recovery.util import human_time

logger = logging.getLogger(__name__)


class PackageFacet:
    """Recovery facet for tracked system packages (distro-agnostic)."""

    name = "packages"

    def __init__(self, manager: PackageManager, packages: tuple[str, ...]) -> None:
        self._manager = manager
        self._packages = packages

    def init(self) -> None:
        Path(PACKAGES_STAMP_FILE).parent.mkdir(parents=True, exist_ok=True)

    def _collect_versions(self) -> dict[str, str]:
        return self._manager.list_installed(self._packages)

    def _read_stamp_file(self) -> dict[str, str]:
        path = Path(PACKAGES_STAMP_FILE)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read packages stamp file")
            return {}

    def _read_factory_file(self) -> dict[str, str]:
        path = Path(FACTORY_PACKAGES_FILE)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read factory packages file")
            return {}

    def _write_stamp_file(self) -> None:
        versions = self._collect_versions()
        path = Path(PACKAGES_STAMP_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(versions, indent=2, sort_keys=True))

    def stamp(self) -> str | None:
        self._write_stamp_file()
        return None

    def available_updates(self) -> list[tuple[str, str, str]]:
        return self._manager.check_updates(self._packages)

    def remote_updates(self) -> list[Item]:
        updates = self.available_updates()
        items = [
            Item(
                name=name,
                label=f"{name} {old_ver}",
                dirty=False,
                right=f"↑{new_ver}",
                actions=[],
            )
            for name, old_ver, new_ver in updates
        ]
        if len(items) > 1:
            items.append(Item(
                name="all",
                label="Update All",
                dirty=False,
                right=f"{len(items)} pkgs",
                actions=[],
            ))
        return items

    def list_items(self) -> list[Item]:
        self.init()
        installed = self._collect_versions()
        stamped = self._read_stamp_file()
        factory = self._read_factory_file()
        available: dict[str, str] = {u[0]: u[2] for u in self.available_updates()}

        stamp_time: datetime | None = None
        stamp_path = Path(PACKAGES_STAMP_FILE)
        if stamp_path.exists():
            try:
                stamp_time = datetime.fromtimestamp(stamp_path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                pass

        items: list[Item] = []
        for pkg in self._packages:
            inst = installed.get(pkg, "not-installed")
            stamp = stamped.get(pkg, "not-installed")
            fact = factory.get(pkg, "not-installed")
            avail = available.get(pkg)
            is_dirty = inst != stamp

            if is_dirty and stamp_time:
                right = human_time(stamp_time)
            elif is_dirty:
                right = "?"
            else:
                right = human_time(stamp_time) if stamp_time else "factory"

            if avail:
                right = f"↑{avail}"

            label = pkg + (" *" if is_dirty else "")
            actions: list[Action] = []
            if avail:
                actions.append(
                    Action(
                        "Update",
                        lambda p=pkg: self._install_single(p),
                        confirm=f"Update {pkg}?",
                    )
                )
            if is_dirty and stamp != "not-installed":
                actions.append(
                    Action(
                        "Rollback to stamp",
                        lambda p=pkg: self.rollback(p, "stamp"),
                        confirm=f"Rollback {pkg}\nto stamp?",
                    )
                )
            if fact != "not-installed":
                actions.append(
                    Action(
                        "Rollback to factory",
                        lambda p=pkg: self.rollback(p, "factory"),
                        confirm=f"Rollback {pkg}\nto factory?",
                    )
                )
            items.append(Item(name=pkg, label=label, dirty=is_dirty, right=right, actions=actions))
        return items

    def _install_single(self, pkg: str) -> None:
        if not self._manager.download([pkg]):
            logger.error("Download failed for %s", pkg)
            return
        if not self._manager.install([pkg]):
            logger.error("Install failed for %s", pkg)
            self._manager.install_from_cache([pkg])
            return
        self.stamp()

    def rollback(self, name: str, target: RollbackTarget) -> None:
        stamped = self._read_stamp_file()
        factory = self._read_factory_file()
        version: str | None = None
        if target == "stamp":
            version = stamped.get(name)
        elif target == "factory":
            version = factory.get(name)
        if not version or version == "not-installed":
            logger.warning("No version found for %s in target %s", name, target)
            return
        logger.info("Rolling back %s to %s", name, version)
        self._manager.install_version(name, version)


def make_package_facet(
    manager: PackageManager | None = None,
    packages: tuple[str, ...] | None = None,
) -> PackageFacet:
    """Return a PackageFacet, auto-detecting the distro if manager is not given."""
    if manager is None:
        manager = detect_package_manager()

    if packages is None:
        from pistomp_recovery.constants import PISTOMP_APT_ORIGIN

        packages = manager.discover_packages(PISTOMP_APT_ORIGIN)

    return PackageFacet(manager, packages)


# Public re-exports used by backends and entry points.
def stamp_packages() -> None:
    make_package_facet().stamp()


def list_package_items() -> list[Item]:
    return make_package_facet().list_items()


def rollback_package(name: str, target: RollbackTarget) -> None:
    make_package_facet().rollback(name, target)


def get_available_updates() -> list[tuple[str, str, str]]:
    return make_package_facet().available_updates()
