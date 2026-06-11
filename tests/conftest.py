"""
Shims for Raspberry Pi / CircuitPython hardware modules unavailable on macOS/Windows.
Injected into sys.modules at import time so application code can be imported in tests.
"""

import os
import sys
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

# Initialize pygame headlessly before any uilib/test imports.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from pistomp_recovery.pygame_init import init as _pg_init
from pistomp_recovery.ui.widgets.misc import InputEvent

_pg_init()

import pygame  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

PROJECT_ROOT = Path(__file__).parent.parent
_TESTS_DIR = Path(__file__).parent
_SNAPSHOT_DIR = _TESTS_DIR / "snapshots"

_PI_MODULES: list[str] = [
    "alsaaudio",
    "board",
    "busio",
    "digitalio",
    "gpiozero",
    "lgpio",
    "rpi_lgpio",
    "neopixel",
    "spidev",
    "lilv",
    "adafruit_mcp3xxx",
    "adafruit_mcp3xxx.analog_in",
    "adafruit_mcp3xxx.mcp3008",
    "adafruit_rgb_display",
    "adafruit_rgb_display.ili9341",
    "adafruit_rgb_display.st7789",
    "adafruit_ssd1306",
]

for _mod in _PI_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ---------------------------------------------------------------------------
# FakeLcd — captures rendered frames without touching hardware
# ---------------------------------------------------------------------------


class FakeLcd:
    """LCD stub that captures every frame pushed via update() into a list.

    Converts pygame Surfaces to PIL Images for snapshot comparison.
    """

    def __init__(self, width: int = 320, height: int = 240) -> None:
        self.width = width
        self.height = height
        self.frames: list[Image.Image] = []
        self._has_splash = False

    @property
    def has_system_splash(self) -> bool:
        return self._has_splash

    def init(self) -> None:
        self._has_splash = True

    def update(self, surface: pygame.Surface) -> None:
        rgb = pygame.image.tostring(surface, "RGB")
        img = Image.frombytes("RGB", (self.width, self.height), rgb)
        self.frames.append(img)

    def clear(self) -> None:
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        self.frames.append(img)


# ---------------------------------------------------------------------------
# FakeEncoder + FakeInputManager — injectable input events for tests
# ---------------------------------------------------------------------------


class FakeEncoder:
    """Encoder stub that queues events for test injection."""

    def __init__(self) -> None:
        self._events: list[int] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def poll(self) -> int:
        if self._events:
            return self._events.pop(0)
        return 0

    def inject(self, direction: int) -> None:
        self._events.append(direction)


class FakeInputManager:
    """InputManager stub backed by FakeEncoder, with click injection."""

    def __init__(self, encoder: FakeEncoder) -> None:
        self._encoder = encoder
        self._click_queue: list[bool] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def inject_click(self, long: bool = False) -> None:
        self._click_queue.append(long)

    def poll(self) -> list[InputEvent]:
        events: list[InputEvent] = []
        direction: int = self._encoder.poll()
        if direction > 0:
            events.append(InputEvent.RIGHT)
        elif direction < 0:
            events.append(InputEvent.LEFT)
        if self._click_queue:
            long = self._click_queue.pop(0)
            events.append(InputEvent.LONG_CLICK if long else InputEvent.CLICK)
        return events


# ---------------------------------------------------------------------------
# RecoveryApp test harness — drives real app with fake hardware
# ---------------------------------------------------------------------------


class AppHarness:
    """Wraps a RecoveryApp with event injection and frame capture."""

    def __init__(self, app: "RecoveryApp", fake_lcd: FakeLcd) -> None:
        self.app = app
        self.lcd = fake_lcd

    def inject(self, *events: InputEvent) -> None:
        """Feed events into the app and redraw if dirty."""
        for ev in events:
            self.app._handle_event(ev)
        if self.app._dirty:
            self.app._draw_current_screen()
            self.app._display.update(self.app._display.surface)
            self.app._dirty = False

    def scroll_to(self, label: str) -> None:
        """Scroll the current menu until the given label is selected."""
        menu = self._current_menu()
        if menu is None:
            return
        for _ in range(len(menu.items) * 2):
            if menu.sel_index < len(menu.items):
                current_label = menu.items[menu.sel_index][0]
                if label in current_label:
                    return
            self.inject(InputEvent.RIGHT)
        raise RuntimeError(f"Could not find menu item: {label}")

    def select(self, label: str) -> None:
        """Scroll to and click a menu item."""
        self.scroll_to(label)
        self.inject(InputEvent.CLICK)

    def long_press(self) -> None:
        self.inject(InputEvent.LONG_CLICK)

    def _current_menu(self) -> "Menu | None":
        screen = self.app._current_screen()
        from pistomp_recovery.ui.screens.menu_screen import MenuScreen
        if isinstance(screen, MenuScreen):
            return screen._menu
        return None

    @property
    def current_screen(self) -> "Screen | None":
        return self.app._current_screen()

    @property
    def surface(self) -> pygame.Surface:
        return self.app._display.surface


@pytest.fixture
def recovery_app(fake_encoder: FakeEncoder, fake_input: FakeInputManager, fake_lcd: FakeLcd, monkeypatch: pytest.MonkeyPatch) -> "Generator[AppHarness, None, None]":
    """Construct a RecoveryApp with fake hardware, initialized and ready to drive."""
    from pistomp_recovery.__main__ import RecoveryApp
    from pistomp_recovery.service import BootMode

    # Prevent subprocess calls during init
    monkeypatch.setattr("pistomp_recovery.__main__.stop_main_app", lambda: True)
    monkeypatch.setattr("pistomp_recovery.__main__.start_main_app", lambda: True)
    # Prevent package/git calls from failing in tests
    monkeypatch.setattr("pistomp_recovery.__main__.list_pedalboard_items", lambda: [])
    monkeypatch.setattr("pistomp_recovery.__main__.list_package_items", lambda: [])
    monkeypatch.setattr("pistomp_recovery.__main__.get_available_updates", lambda: [])
    monkeypatch.setattr("pistomp_recovery.__main__.list_config_items", lambda: [])
    monkeypatch.setattr("pistomp_recovery.__main__.list_system_items", lambda: [])

    app = RecoveryApp(BootMode.USER_RECOVERY)
    # Swap in fakes before init
    app._encoder = fake_encoder
    app._input = fake_input
    app._display._lcd = fake_lcd  # type: ignore[union-attr]
    app.init()

    harness = AppHarness(app, fake_lcd)
    yield harness
    app.cleanup()


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--snapshot-update",
        action="store_true",
        default=False,
        help="Overwrite stored snapshots with current output",
    )


@pytest.fixture
def snapshot_update(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--snapshot-update"))


def assert_snapshot(
    image: Image.Image,
    name: str,
    *,
    update: bool = False,
) -> None:
    path = _SNAPSHOT_DIR / f"{name}.png"
    rgb = image.convert("RGB")
    if update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        rgb.save(path)
        return
    expected = Image.open(path).convert("RGB")
    assert rgb.tobytes() == expected.tobytes(), (
        f"Snapshot mismatch: {name} (re-run with --snapshot-update to accept)"
    )


@pytest.fixture
def snapshot(
    request: pytest.FixtureRequest, fake_lcd: FakeLcd, snapshot_update: bool
) -> Callable[..., None]:
    """Assert the latest LCD frame matches a stored PNG snapshot.

    Path is auto-derived from the test file and function name.
    Call snapshot() for auto-numbered frames or snapshot("label") for named ones.
    Re-use the same label to assert the screen returned to an earlier state.
    """
    counter = [0]
    rel = Path(request.path).relative_to(_TESTS_DIR)
    module: str = str(rel.with_suffix(""))
    test: str = str(request.node.name)  # type: ignore[union-attr]

    def _assert(suffix: str | None = None) -> None:
        if suffix is None:
            suffix = str(counter[0])
            counter[0] += 1
        assert_snapshot(
            fake_lcd.frames[-1],
            f"{module}/{test}/{suffix}",
            update=snapshot_update,
        )

    return _assert


@pytest.fixture
def fake_lcd() -> FakeLcd:
    return FakeLcd()


@pytest.fixture
def fake_encoder() -> FakeEncoder:
    return FakeEncoder()


@pytest.fixture
def fake_input(fake_encoder: FakeEncoder) -> FakeInputManager:
    return FakeInputManager(fake_encoder)
