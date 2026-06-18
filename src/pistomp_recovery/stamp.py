from __future__ import annotations

import argparse
from pathlib import Path

from pistomp_recovery.facet import all_facets

FACET_ORDER: tuple[str, ...] = ("pedalboards", "packages", "config", "system")


def cmd_stamp(args: argparse.Namespace) -> None:
    """Stamp current state as known-good across all facets.

    When ``pedalboard_bundle`` is given, the pedalboards facet stamps only
    that single pedalboard so per-pedalboard timestamps are preserved.
    Other facets are always stamped globally.
    """
    facets = all_facets()
    for name in FACET_ORDER:
        facet = facets.get(name)
        if facet is None:
            continue
        if name == "pedalboards" and args.pedalboard_bundle:
            name_arg = Path(args.pedalboard_bundle).name
            tag: str | None = facet.stamp_item(name_arg)  # type: ignore[union-attr]
            if tag:
                print(f"stamped {name}/{name_arg}: {tag[:8]}")
            else:
                print(f"stamped {name}/{name_arg}")
        else:
            tag = facet.stamp()
            if tag:
                print(f"stamped {name}: {tag[:8]}")
            else:
                print(f"stamped {name}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show dirty state across all facets."""
    facets = all_facets()
    for name in FACET_ORDER:
        facet = facets.get(name)
        if facet is None:
            continue
        items = facet.list_items()
        if any(i.dirty for i in items):
            print(f"{name}:")
            for item in items:
                marker = " *" if item.dirty else ""
                print(f"  {item.label}{marker}  {item.right}")
        else:
            print(f"{name}: clean")


def main(args: list[str] | None = None) -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="pistomp stamp utility")
    parser.add_argument(
        "command",
        choices=["stamp", "status"],
        help="Action to perform",
    )
    parser.add_argument(
        "pedalboard_bundle",
        type=str,
        nargs="?",
        default=None,
        help="Pedalboard bundle path to stamp individually (preserves per-pedalboard timestamps)",
    )

    parsed: argparse.Namespace = parser.parse_args(args)
    if parsed.command == "stamp":
        cmd_stamp(parsed)
    elif parsed.command == "status":
        cmd_status(parsed)


if __name__ == "__main__":
    main()
