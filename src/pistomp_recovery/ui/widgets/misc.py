from __future__ import annotations

from enum import Enum, auto

import pygame


class InputEvent(Enum):
    LEFT = auto()
    RIGHT = auto()
    CLICK = auto()
    LONG_CLICK = auto()
    BACK = auto()


class Box:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x: int = x
        self.y: int = y
        self.w: int = w
        self.h: int = h

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def intersects(self, other: "Box") -> bool:
        return (
            self.x < other.right
            and self.right > other.x
            and self.y < other.bottom
            and self.bottom > other.y
        )

    def union(self, other: "Box") -> "Box":
        x: int = min(self.x, other.x)
        y: int = min(self.y, other.y)
        r: int = max(self.right, other.right)
        b: int = max(self.bottom, other.bottom)
        return Box(x, y, r - x, b - y)

    def clip(self, other: "Box") -> "Box | None":
        x: int = max(self.x, other.x)
        y: int = max(self.y, other.y)
        r: int = min(self.right, other.right)
        b: int = min(self.bottom, other.bottom)
        if r <= x or b <= y:
            return None
        return Box(x, y, r - x, b - y)

    def offset(self, dx: int, dy: int) -> "Box":
        return Box(self.x + dx, self.y + dy, self.w, self.h)

    def is_empty(self) -> bool:
        """True if this rect has zero area (w or h <= 0)."""
        return self.w <= 0 or self.h <= 0

    def to_pygame_rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.w, self.h)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Box):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.w == other.w and self.h == other.h

    def __repr__(self) -> str:
        return f"Box({self.x},{self.y},{self.w},{self.h})"


def union_rects(rects: list[Box]) -> Box | None:
    """Bounding box of a list of rects; None if empty or all empty."""
    acc: Box | None = None
    for r in rects:
        if r.is_empty():
            continue
        acc = r if acc is None else acc.union(r)
    return acc
