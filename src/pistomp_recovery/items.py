from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Action:
    label: str
    callback: Callable[[], None]
    confirm: str | None = None


@dataclass
class Item:
    name: str
    label: str
    dirty: bool
    right: str
    actions: list[Action]


@dataclass(frozen=True)
class Target:
    """One selectable reticule within a :class:`Row`.

    A target is rendered as plain text; when selected it is drawn in reverse
    video (a light box with blue text) instead of literal ``[brackets]``.
    ``confirm`` text, if set, pops a modal before ``on_select`` runs.
    Disabled targets render dimmed and are skipped during navigation.
    """

    label: str
    on_select: Callable[[], object]
    confirm: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class Row:
    """One text line of a menu: optional static ``prefix`` then N targets.

    Targets are joined visually by " | " separators, so a line like
    ``RESTART [JACK] | [MOD]`` is ``Row((Target("JACK", ...),
    Target("MOD", ...)), prefix="RESTART ")``. A plain single-action line is
    just ``Row((Target(...),))``. ``right`` is an optional right-aligned badge.

    ``separator=True`` renders the row dimmed and skips it during navigation.
    """

    targets: tuple[Target, ...] = field(default_factory=tuple)
    prefix: str = ""
    right: str = ""
    separator: bool = False


@dataclass
class PackageUpdate:
    """A pending package update returned by a data backend."""

    name: str
    old_version: str
    new_version: str
