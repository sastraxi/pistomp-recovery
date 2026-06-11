from __future__ import annotations

from dataclasses import dataclass
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
