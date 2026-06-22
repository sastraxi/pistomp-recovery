from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pistomp_recovery.packages.manager import PackageManager

from pistomp_recovery.items import Item

RollbackTarget = Literal["factory", "stamp"]


@runtime_checkable
class Facet(Protocol):
    """Common interface for all recovery facets.

    Each facet represents one domain that pi-stomp can snapshot, roll back,
    or inspect for drift: config files, system files, pedalboards, and
    packages.
    """

    name: str

    def init(self) -> None:
        """Initialize any backing storage (git repo, stamp file, etc.)."""
        ...

    def list_items(self) -> list[Item]:
        """Return the list of items currently visible in this facet."""
        ...

    def stamp(self) -> str | None:
        """Snapshot the current state of the facet. Returns a tag/id or None."""
        ...

    def rollback(self, name: str, target: RollbackTarget) -> None:
        """Rollback one item to ``target`` ("factory" or "stamp")."""
        ...

    def remote_updates(self) -> list[Item]:
        """Return items with pending remote updates and their action callbacks.

        Items returned here appear under the Updates menu for this facet's
        domain.  Each item should carry an ``Action("Update", ...)`` if
        the facet can apply the update itself.  A facet that has no remote
        update concept (e.g. local-only config files) returns an empty list.
        """
        return []


_FACETS: dict[str, Facet] = {}


def register_facet(name: str, facet: Facet) -> None:
    """Register a facet implementation under its domain name."""
    _FACETS[name] = facet


def get_facet(name: str) -> Facet | None:
    """Look up a registered facet by domain name."""
    return _FACETS.get(name)


def all_facets() -> dict[str, Facet]:
    """Return a copy of the registered facet map."""
    return dict(_FACETS)


def clear_facets() -> None:
    """Remove all registered facets. Useful for tests and emulator resets."""
    _FACETS.clear()


def register_default_facets(
    manager: PackageManager | None = None,
) -> None:
    """Register the real device facets (config, system, pedalboards, packages).

    Entry points that run on the pi-Stomp should call this before using
    ``all_facets()`` or ``get_facet()``.  Pass a ``PackageManager`` to share
    the same detected instance with ``RealDataBackend``; omit it to
    auto-detect.
    """
    from pistomp_recovery.config import make_config_facet
    from pistomp_recovery.packages.packages import make_package_facet
    from pistomp_recovery.pedalboards import make_pedalboard_facet
    from pistomp_recovery.system import make_system_facet

    register_facet("config", make_config_facet())
    register_facet("system", make_system_facet())
    register_facet("pedalboards", make_pedalboard_facet())
    register_facet("packages", make_package_facet(manager))
