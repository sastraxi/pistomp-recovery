from __future__ import annotations

import logging
import shutil
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

from pistomp_recovery.constants import (
    FACTORY_LV2_BUNDLES_FILE,
    LV2_PLUGINS_URL,
    PATCHSTORAGE_MARKER,
    PLUGINS_CACHE_WARN_BYTES,
    PLUGINS_DIR,
    PLUGINS_STAMP_FILE,
)
from pistomp_recovery.facet import RollbackTarget
from pistomp_recovery.items import Action, Item
from pistomp_recovery.util import human_size

ProgressCallback = Callable[[str, float, str, bool], None]

logger = logging.getLogger(__name__)


def _dir_size(path: Path) -> int:
    """Total size in bytes of all files under ``path`` (symlinks not followed)."""
    total: int = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def _read_names(path: str | Path) -> set[str]:
    """Read a one-name-per-line file into a set. Missing file = empty set."""
    p = Path(path)
    if not p.is_file():
        return set()
    names: set[str] = set()
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line)
    return names


class PluginFacet:
    """Recovery facet for user-installed LV2 plugins.

    Plugins are delivered and updated by mod-ui's PatchStorage downloader, not
    by recovery.  This facet provides two recovery operations:

    * **Factory Reset** — delete a user-installed bundle so the system LV2 path
      (factory plugins) takes over.  A factory-allowlist file
      (``FACTORY_LV2_BUNDLES_FILE``, one bundle dir name per line) protects
      bundles shipped in the image even if they carry the PatchStorage marker.
    * **Reset to Checkpoint** — delete bundles installed *since* the last
      stamp.  The stamp is an append-only known-good set of bundle dir names
      in ``PLUGINS_STAMP_FILE``; ``pistomp-stamp stamp --plugin <name>`` adds
      one entry (called by mod-ui after a successful install), and a full
      ``pistomp-stamp stamp`` snapshots the current set.  Bundles that were
      stamped but are now missing are shown as informational (non-clickable)
      rows — they can't be restored without re-downloading.

    A bundle counts as user-installed (and therefore visible to recovery) when
    it carries the ``patchstorage.json`` marker mod-ui writes on install.
    Factory plugins live in the system LV2 path, outside ``PLUGINS_DIR``, and
    are never touched.  The allowlist is a defence-in-depth against factory
    bundles that ship with the marker (e.g. an ``lv2plugins.tar.gz`` produced
    by mod-ui's installer).
    """

    name = "plugins"
    default_path: Path = Path(PLUGINS_DIR)
    default_stamp_file: str = PLUGINS_STAMP_FILE
    default_allowlist_file: str = FACTORY_LV2_BUNDLES_FILE

    def __init__(
        self,
        path: Path | None = None,
        stamp_file: str | Path | None = None,
        allowlist_file: str | Path | None = None,
    ) -> None:
        self.path = path or self.default_path
        self._stamp_file: Path = Path(stamp_file) if stamp_file else Path(self.default_stamp_file)
        self._allowlist_file: Path = (
            Path(allowlist_file) if allowlist_file else Path(self.default_allowlist_file)
        )

    def init(self) -> None:
        # The plugins dir is created by mod-ui on first install; nothing to set
        # up here. Kept for Facet-protocol compatibility.
        return None

    # -- stamp set ----------------------------------------------------------

    def _read_stamp(self) -> set[str]:
        return _read_names(self._stamp_file)

    def _append_stamp(self, name: str) -> None:
        """Append a single bundle name to the stamp file (idempotent)."""
        self._stamp_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_stamp()
        if name in existing:
            return
        with self._stamp_file.open("a") as f:
            f.write(f"{name}\n")

    def stamp(self) -> str | None:
        """Snapshot the current user-bundle set into the stamp file.

        Appends all current bundle names that aren't already stamped.  This
        is additive — a full stamp never forgets a previously-stamped bundle,
        so rolling back to stamp after a stamp always keeps the older set.
        """
        names = {b.name for b in self._user_bundles()}
        if not names:
            return None
        self._stamp_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_stamp()
        new = names - existing
        if not new:
            return None
        with self._stamp_file.open("a") as f:
            for name in sorted(new):
                f.write(f"{name}\n")
        return None

    def stamp_item(self, name: str) -> str | None:
        """Stamp a single bundle by directory name (called by mod-ui)."""
        self._append_stamp(name)
        return None

    # -- factory allowlist --------------------------------------------------

    def _factory_names(self) -> set[str]:
        return _read_names(self._allowlist_file)

    # -- bundle enumeration --------------------------------------------------

    def _user_bundles(self) -> list[Path]:
        """Return LV2 bundle dirs carrying the PatchStorage marker, sorted by name."""
        if not self.path.is_dir():
            return []
        bundles: list[Path] = []
        for entry in sorted(self.path.iterdir()):
            if entry.is_dir() and (entry / PATCHSTORAGE_MARKER).is_file():
                bundles.append(entry)
        return bundles

    def cache_size(self) -> int:
        """Total bytes occupied by user-installed plugin bundles."""
        return sum(_dir_size(b) for b in self._user_bundles())

    def over_cap(self) -> bool:
        """True if the plugins cache exceeds the soft warning threshold."""
        return self.cache_size() > PLUGINS_CACHE_WARN_BYTES

    def cache_summary(self) -> str:
        """Short right-aligned badge for the Plugins menu line (size, with warning if over cap)."""
        bundles = self._user_bundles()
        if not bundles:
            return ""
        size = sum(_dir_size(b) for b in bundles)
        label = human_size(size)
        return f"{label} \u26a0" if size > PLUGINS_CACHE_WARN_BYTES else label

    def remote_updates(self) -> list[Item]:
        """Plugin updates are owned by mod-ui's PatchStorage downloader, not recovery."""
        return []

    # -- item model ---------------------------------------------------------

    def list_items(self) -> list[Item]:
        stamped = self._read_stamp()
        factory = self._factory_names()
        has_stamp_file = self._stamp_file.is_file()
        current_names = {b.name for b in self._user_bundles()}

        items: list[Item] = []

        # Present user bundles.
        for bundle in self._user_bundles():
            name = bundle.name
            is_new = name not in stamped if has_stamp_file else True
            in_factory = name in factory
            size = human_size(_dir_size(bundle))

            actions: list[Action] = []
            # Checkpoint: delete bundles installed since the last stamp.
            if is_new and has_stamp_file:
                actions.append(
                    Action(
                        "Rollback to stamp",
                        lambda n=name: self.rollback(n, "stamp"),
                        confirm=f"Delete {name}?\nIt was installed since the last stamp.",
                    )
                )
            # Factory: delete the bundle. Refuse if it's in the factory allowlist.
            if not in_factory:
                actions.append(
                    Action(
                        "Rollback to factory",
                        lambda n=name: self.rollback(n, "factory"),
                        confirm=f"Delete {name}?\nFactory plugins are unaffected.",
                    )
                )
            # If in factory allowlist, no actions — bundle is protected.

            items.append(
                Item(
                    name=name,
                    label=name,
                    dirty=is_new,
                    right=size,
                    actions=actions,
                )
            )

        # Missing bundles: stamped but no longer on disk. Informational only.
        missing = stamped - current_names
        for name in sorted(missing):
            items.append(
                Item(
                    name=name,
                    label=name,
                    dirty=False,
                    right="missing",
                    actions=[],
                )
            )

        return items

    # -- mutations ----------------------------------------------------------

    def remove_bundle(self, name: str) -> None:
        """Delete a single user-installed bundle by directory name.

        Refuses to delete a bundle in the factory allowlist, even if it carries
        the PatchStorage marker (defence against factory-shipped bundles).
        """
        factory = self._factory_names()
        if name in factory:
            logger.warning("Refusing to remove %s: it is in the factory allowlist", name)
            return
        bundle = self.path / name
        if (bundle / PATCHSTORAGE_MARKER).is_file():
            shutil.rmtree(bundle, ignore_errors=True)
            logger.info("Removed plugin bundle %s", name)
        else:
            logger.warning("Refusing to remove %s: not a PatchStorage bundle", name)

    def reset_all(self) -> None:
        """Remove every user-installed bundle not in the factory allowlist."""
        for bundle in self._user_bundles():
            self.remove_bundle(bundle.name)

    def rollback(self, name: str, target: RollbackTarget) -> None:
        # Plugins have no per-stamp content history; both targets mean "delete
        # the user-installed bundle." Factory plugins live in the system LV2
        # path and are unaffected.
        self.remove_bundle(name)

    # -- factory plugin restore ----------------------------------------------

    def factory_plugin_count(self) -> int:
        """Count of factory plugin bundles (from allowlist, or dir scan fallback)."""
        names = self._factory_names()
        if names:
            return len(names)
        if not self.path.is_dir():
            return 0
        return sum(
            1 for e in self.path.iterdir()
            if e.is_dir() and not (e / PATCHSTORAGE_MARKER).is_file()
        )

    def fetch_factory_size(self) -> int | None:
        """HEAD the factory archive URL; return Content-Length in bytes, or None."""
        try:
            req = urllib.request.Request(LV2_PLUGINS_URL, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                cl = resp.headers.get("Content-Length")
                return int(cl) if cl else None
        except Exception:
            logger.debug("Could not fetch factory archive size", exc_info=True)
            return None

    def reset_factory_plugins(self, progress: ProgressCallback) -> bool:
        """Stream-download and untar the factory plugin archive over PLUGINS_DIR.

        Extracts additively — existing bundles not in the archive are untouched.
        """
        try:
            progress("Connecting", 0.0, "Opening download...", False)
            resp = urllib.request.urlopen(LV2_PLUGINS_URL, timeout=60)
            total = int(resp.headers.get("Content-Length") or 0)
            read_so_far = [0]

            class _Reader:
                def read(self, n: int) -> bytes:
                    chunk = resp.read(n)
                    read_so_far[0] += len(chunk)
                    return chunk

            dest = self.path.resolve().parent
            dest.mkdir(parents=True, exist_ok=True)

            with tarfile.open(fileobj=_Reader(), mode="r|gz") as tf:  # type: ignore[arg-type]
                for member in tf:  # type: ignore[assignment]
                    tf.extract(member, path=dest, filter="data")  # type: ignore[call-arg]
                    if total:
                        frac = min(read_so_far[0] / total, 0.99)
                        name: str = str(member.name).split("/")[-1] or "..."  # type: ignore[attr-defined]
                        progress("Downloading", frac, name, False)

            progress("Done", 1.0, "Click to continue.", True)
            return True
        except Exception:
            logger.exception("Factory plugin reset failed")
            progress("Failed", 0.0, "Click to continue.", True)
            return False


def make_plugin_facet(
    path: Path | None = None,
    stamp_file: str | Path | None = None,
    allowlist_file: str | Path | None = None,
) -> PluginFacet:
    """Return a fresh plugin facet for registration by an entry point."""
    return PluginFacet(path, stamp_file, allowlist_file)
