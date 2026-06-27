from __future__ import annotations

import argparse
from pathlib import Path

from pistomp_recovery.facet import all_facets, register_default_facets

FACET_ORDER: tuple[str, ...] = ("pedalboards", "plugins", "packages", "config", "boot")


def cmd_stamp(args: argparse.Namespace) -> None:
    """Stamp current state as known-good across all facets.

    When ``--pedalboard <bundle>`` is given, the pedalboards facet stamps only
    that single pedalboard so per-pedalboard timestamps are preserved.
    When ``--plugin <name>`` is given, the plugins facet stamps only that
    single bundle (appends its dir name to the known-good set).
    Other facets are always stamped globally.
    """
    facets = all_facets()
    for name in FACET_ORDER:
        facet = facets.get(name)
        if facet is None:
            continue
        pedalboard_arg = args.pedalboard or getattr(args, "bundle", None)
        if name == "pedalboards" and pedalboard_arg:
            name_arg = Path(pedalboard_arg).name
            tag: str | None = facet.stamp_item(name_arg)  # type: ignore[union-attr]
            if tag:
                print(f"stamped {name}/{name_arg}: {tag[:8]}")
            else:
                print(f"stamped {name}/{name_arg}")
        elif name == "plugins" and args.plugin:
            tag = facet.stamp_item(args.plugin)  # type: ignore[union-attr]
            if tag:
                print(f"stamped {name}/{args.plugin}: {tag[:8]}")
            else:
                print(f"stamped {name}/{args.plugin}")
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
    sub = parser.add_subparsers(dest="command", required=True)

    stamp_parser = sub.add_parser("stamp", help="Stamp current state as known-good")
    stamp_parser.add_argument(
        "bundle",
        nargs="?",
        default=None,
        help="Pedalboard bundle path to stamp individually (positional form of --pedalboard)",
    )
    stamp_parser.add_argument(
        "--pedalboard",
        type=str,
        default=None,
        help="Pedalboard bundle path to stamp individually",
    )
    stamp_parser.add_argument(
        "--plugin",
        type=str,
        default=None,
        help="Plugin bundle dir name to stamp individually (appends to known-good set)",
    )

    sub.add_parser("status", help="Show dirty state across all facets")

    parsed = parser.parse_args(args)

    register_default_facets()

    if parsed.command == "stamp":
        cmd_stamp(parsed)
    elif parsed.command == "status":
        cmd_status(parsed)


if __name__ == "__main__":
    main()
