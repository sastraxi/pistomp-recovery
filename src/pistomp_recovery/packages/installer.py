from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def download_packages(names: list[str]) -> bool:
    """pacman -Sw --noconfirm --needed. Returns True on success."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["pacman", "-Sw", "--noconfirm", "--needed"] + names,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Package download failed: %s", result.stderr)
        return False
    return True


def install_packages(names: list[str]) -> bool:
    """pacman -S --noconfirm --needed. Returns True on success."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["pacman", "-S", "--noconfirm", "--needed"] + names,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Package install failed: %s", result.stderr)
        return False
    return True


def install_from_cache(names: list[str]) -> bool:
    """Find cached .pkg.tar* and pacman -U. Returns True on success."""
    cached: list[str] = []
    for pkg in names:
        cache_result: subprocess.CompletedProcess[str] = subprocess.run(
            ["pacman", "-Qp", f"/var/cache/pacman/pkg/{pkg}-*.pkg.tar*"],
            capture_output=True,
            text=True,
        )
        if cache_result.returncode == 0:
            cached.append(pkg)
    if not cached:
        logger.warning("No cached packages found for rollback")
        return False
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["pacman", "-U", "--noconfirm"] + cached,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Rollback install failed: %s", result.stderr)
        return False
    return True
