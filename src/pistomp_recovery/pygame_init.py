"""Idempotent pygame + pygame._freetype initialization.

Use pygame._freetype (the C extension) rather than pygame.freetype:
the public pygame.freetype module triggers a circular import with
pygame.font on Python 3.14 / pygame 2.6.1.
"""

from __future__ import annotations

import os
import threading

_initialized: bool = False
_lock = threading.Lock()


def init(headless: bool = True) -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        if headless and "SDL_VIDEODRIVER" not in os.environ:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
        import pygame
        import pygame._freetype as _freetype

        pygame.init()
        _freetype.init()  # type: ignore[union-attr]
        _initialized = True
