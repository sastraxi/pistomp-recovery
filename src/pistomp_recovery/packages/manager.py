"""Distro-agnostic package manager abstraction.

`PackageManager` is a structural Protocol; `PacmanManager` and `AptManager`
implement it for Arch Linux and Debian/Raspbian respectively.
`detect_package_manager()` picks the right one at runtime.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class PackageManager(Protocol):
    """Minimal operations needed to query, install, and roll back packages."""

    def list_installed(self, names: tuple[str, ...]) -> dict[str, str]:
        """Return name→version for each tracked package ("not-installed" if absent)."""
        ...

    def sync_db(self) -> bool:
        """Sync the package DB (apt-get update / pacman -Sy). Returns True on success."""
        ...

    def check_updates(self, names: tuple[str, ...]) -> list[tuple[str, str, str]]:
        """Return (name, old_ver, new_ver) for upgradeable packages.

        Calls sync_db() lazily if it has not already been called this session.
        """
        ...

    def download(self, names: list[str]) -> bool:
        """Pre-download packages without installing. Returns True on success."""
        ...

    def install(self, names: list[str]) -> bool:
        """Install packages from the remote repo. Returns True on success."""
        ...

    def install_from_cache(self, names: list[str]) -> bool:
        """Install from the local package cache (used to roll back a failed install)."""
        ...

    def install_version(self, name: str, version: str) -> bool:
        """Install a specific version of a package (for stamp/factory rollback)."""
        ...


class PacmanManager:
    """PackageManager backed by pacman (Arch Linux / Arch Linux ARM)."""

    def __init__(self) -> None:
        self._synced: bool = False

    def list_installed(self, names: tuple[str, ...]) -> dict[str, str]:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["pacman", "-Q"], capture_output=True, text=True, check=False
        )
        all_pkgs: dict[str, str] = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                all_pkgs[parts[0]] = parts[1].strip()
        return {name: all_pkgs.get(name, "not-installed") for name in names}

    def sync_db(self) -> bool:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "pacman", "-Sy"], capture_output=True, check=False, text=True
        )
        self._synced = True
        return result.returncode == 0

    def check_updates(self, names: tuple[str, ...]) -> list[tuple[str, str, str]]:
        if not self._synced:
            self.sync_db()
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["pacman", "-Qu", *names], capture_output=True, text=True, check=False
        )
        updates: list[tuple[str, str, str]] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 3:
                updates.append((parts[0], parts[1], parts[2]))
            elif len(parts) == 2:
                updates.append((parts[0], "unknown", parts[1]))
        return updates

    def download(self, names: list[str]) -> bool:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "pacman", "-Sw", "--noconfirm", "--needed", *names],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("pacman download failed: %s", result.stderr)
            return False
        return True

    def install(self, names: list[str]) -> bool:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "pacman", "-S", "--noconfirm", "--needed", *names],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("pacman install failed: %s", result.stderr)
            return False
        return True

    def install_from_cache(self, names: list[str]) -> bool:
        cache = Path("/var/cache/pacman/pkg")
        cached_files: list[str] = []
        for pkg in names:
            matches = sorted(cache.glob(f"{pkg}-*.pkg.tar*"))
            if matches:
                cached_files.append(str(matches[-1]))
        if not cached_files:
            logger.warning("No cached packages found for: %s", names)
            return False
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "pacman", "-U", "--noconfirm", *cached_files],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("pacman cache install failed: %s", result.stderr)
            return False
        return True

    def install_version(self, name: str, version: str) -> bool:
        cache = Path("/var/cache/pacman/pkg")
        matches = sorted(cache.glob(f"{name}-{version}-*.pkg.tar*"))
        if matches:
            result: subprocess.CompletedProcess[str] = subprocess.run(
                ["sudo", "pacman", "-U", "--noconfirm", str(matches[0])],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
            logger.error("pacman version install failed: %s", result.stderr)
        logger.warning("Version %s for %s not found in cache", version, name)
        return False


class AptManager:
    """PackageManager backed by apt/dpkg (Debian, Raspbian, Ubuntu)."""

    def __init__(self) -> None:
        self._synced: bool = False

    def list_installed(self, names: tuple[str, ...]) -> dict[str, str]:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}\t${db:Status-Abbrev}\t${Version}\n"],
            capture_output=True,
            text=True,
            check=False,
        )
        installed: dict[str, str] = {}
        name_set = set(names)
        for line in result.stdout.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) == 3:
                pkg, status, version = parts[0], parts[1], parts[2].strip()
                if pkg in name_set and status.startswith("ii"):
                    installed[pkg] = version
        return {name: installed.get(name, "not-installed") for name in names}

    def sync_db(self) -> bool:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "apt-get", "update", "-qq"], capture_output=True, check=False, text=True
        )
        self._synced = True
        return result.returncode == 0

    def check_updates(self, names: tuple[str, ...]) -> list[tuple[str, str, str]]:
        if not self._synced:
            self.sync_db()
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["apt", "list", "--upgradeable"],
            capture_output=True,
            text=True,
            check=False,
        )
        name_set = set(names)
        updates: list[tuple[str, str, str]] = []
        pattern = re.compile(
            r"^([^/\s]+)/\S+\s+(\S+)\s+\S+\s+\[upgradable from:\s+([^\]]+)\]"
        )
        for line in result.stdout.split("\n"):
            m = pattern.match(line)
            if m and m.group(1) in name_set:
                updates.append((m.group(1), m.group(3), m.group(2)))
        return updates

    def download(self, names: list[str]) -> bool:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "apt-get", "install", "--download-only", "-y", *names],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("apt download failed: %s", result.stderr)
            return False
        return True

    def install(self, names: list[str]) -> bool:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "apt-get", "install", "-y", *names],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("apt install failed: %s", result.stderr)
            return False
        return True

    def install_from_cache(self, names: list[str]) -> bool:
        cache = Path("/var/cache/apt/archives")
        deb_files: list[str] = []
        for pkg in names:
            matches = sorted(cache.glob(f"{pkg}_*.deb"))
            if matches:
                deb_files.append(str(matches[-1]))
        if not deb_files:
            logger.warning("No cached .deb files found for: %s", names)
            return False
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["sudo", "dpkg", "-i", *deb_files],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("dpkg cache install failed: %s", result.stderr)
            return False
        return True

    def install_version(self, name: str, version: str) -> bool:
        # Try local cache first (Debian encodes ":" as "%3a" in filenames)
        safe_ver = version.replace(":", "%3a")
        cache = Path("/var/cache/apt/archives")
        matches = sorted(cache.glob(f"{name}_{safe_ver}_*.deb"))
        if matches:
            result: subprocess.CompletedProcess[str] = subprocess.run(
                ["sudo", "dpkg", "-i", str(matches[0])],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return True
            logger.warning("dpkg cache install failed, trying apt: %s", result.stderr)

        result = subprocess.run(
            [
                "sudo",
                "apt-get",
                "install",
                "-y",
                "--allow-downgrades",
                f"{name}={version}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("apt version install failed: %s", result.stderr)
            return False
        return True


def detect_package_manager() -> PacmanManager | AptManager:
    """Return the appropriate PackageManager for this system."""
    if shutil.which("pacman"):
        return PacmanManager()
    if shutil.which("apt-get"):
        return AptManager()
    raise RuntimeError(
        "No supported package manager found (expected pacman or apt-get)"
    )
