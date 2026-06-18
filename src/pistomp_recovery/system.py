from __future__ import annotations

from pathlib import Path

from pistomp_recovery.constants import RECOVERY_DIR
from pistomp_recovery.file_facet import FileFacet

SYSTEM_FILES: tuple[str, ...] = (
    "/boot/config.txt",
    "/boot/cmdline.txt",
    "/boot/pistomp.conf",
    "/etc/jackdrc",
    "/var/lib/alsa/asound.state",
)
SYSTEM_REPO: Path = Path(RECOVERY_DIR) / "system.git"

_SOURCE_BY_NAME: dict[str, str] = {Path(p).name: p for p in SYSTEM_FILES}


def make_system_facet() -> FileFacet:
    """Return a system FileFacet for registration by an entry point."""
    return FileFacet(
        name="system",
        repo_dir=SYSTEM_REPO,
        files=tuple(_SOURCE_BY_NAME.keys()),
        source_resolver=lambda name: Path(_SOURCE_BY_NAME[name]),
        display_name_resolver=lambda name: name,
    )
