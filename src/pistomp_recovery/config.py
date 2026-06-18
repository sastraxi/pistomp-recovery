from __future__ import annotations

from pathlib import Path

from pistomp_recovery.constants import CONFIG_DIR, RECOVERY_DIR
from pistomp_recovery.file_facet import FileFacet

CONFIG_FILES: tuple[str, ...] = (
    "default_config.yml",
    "settings.yml",
)
CONFIG_REPO: Path = Path(RECOVERY_DIR) / "config.git"


def make_config_facet() -> FileFacet:
    """Return a config FileFacet for registration by an entry point."""
    return FileFacet(
        name="config",
        repo_dir=CONFIG_REPO,
        files=CONFIG_FILES,
        source_resolver=lambda filename: Path(CONFIG_DIR) / filename,
        display_name_resolver=lambda filename: filename,
    )
