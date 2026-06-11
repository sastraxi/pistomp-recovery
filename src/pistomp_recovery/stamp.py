from __future__ import annotations

import argparse

from pistomp_recovery.packages import stamp_packages
from pistomp_recovery.pedalboards import init_pedalboards, stamp_pedalboard_repo


def cmd_stamp(args: argparse.Namespace) -> None:
    """Stamp current state as known-good."""
    from pathlib import Path

    from pistomp_recovery.constants import PEDALBOARDS_DIR

    init_pedalboards(Path(PEDALBOARDS_DIR))
    tag: str = stamp_pedalboard_repo(Path(PEDALBOARDS_DIR))
    stamp_packages()
    print(f"stamped pedalboards: {tag}")
    print("stamped packages")


def cmd_status(args: argparse.Namespace) -> None:
    """Show dirty state."""
    from pathlib import Path

    from pistomp_recovery.config import list_config_items
    from pistomp_recovery.constants import PEDALBOARDS_DIR
    from pistomp_recovery.packages import list_package_items
    from pistomp_recovery.pedalboards import init_pedalboards, list_pedalboard_items
    from pistomp_recovery.system import list_system_items

    init_pedalboards(Path(PEDALBOARDS_DIR))
    pb_items = list_pedalboard_items(Path(PEDALBOARDS_DIR))
    if pb_items:
        print("pedalboards:")
        for item in pb_items:
            marker: str = " *" if item.dirty else ""
            print(f"  {item.label}{marker}  {item.right}")
    else:
        print("pedalboards: clean")

    pkg_items = list_package_items()
    if any(i.dirty for i in pkg_items):
        print("packages:")
        for item in pkg_items:
            marker = " *" if item.dirty else ""
            print(f"  {item.label}{marker}  {item.right}")
    else:
        print("packages: clean")

    cfg = list_config_items()
    if cfg and cfg[0].dirty:
        print(f"config: {cfg[0].label}  {cfg[0].right}")
    else:
        print("config: clean")

    sys_items = list_system_items()
    if sys_items and sys_items[0].dirty:
        print(f"system: {sys_items[0].label}  {sys_items[0].right}")
    else:
        print("system: clean")


def main(args: list[str] | None = None) -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="pistomp stamp utility"
    )
    parser.add_argument(
        "command",
        choices=["stamp", "status"],
        help="Action to perform",
    )

    parsed: argparse.Namespace = parser.parse_args(args)
    if parsed.command == "stamp":
        cmd_stamp(parsed)
    elif parsed.command == "status":
        cmd_status(parsed)


if __name__ == "__main__":
    main()
