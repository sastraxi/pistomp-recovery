# pyright: reportPrivateUsage=false, reportUnusedFunction=false
"""Test fixtures using dependency-injected fake backends.

Shims for Raspberry Pi / CircuitPython hardware modules unavailable on macOS/Windows.
Injected into sys.modules at import time so application code can be imported in tests.
"""

import os
import sys
import time
from pathlib import Path
from typing import Callable, Generator
from unittest.mock import MagicMock

# Initialize pygame headlessly before any uilib/test imports.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from pistomp_recovery.pygame_init import init as _pg_init  # noqa: E402

_pg_init()

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from pistomp_recovery.app import RecoveryAppCore  # noqa: E402
from pistomp_recovery.backends import AppBackends, DataBackend, DisplayBackend  # noqa: E402
from pistomp_recovery.items import Item, PackageUpdate  # noqa: E402
from pistomp_recovery.service import BootMode, CrashInfo  # noqa: E402
from pistomp_recovery.ui.screens.menu_screen import MenuScreen as MS  # noqa: E402
from pistomp_recovery.ui.widgets.misc import Box, InputEvent  # noqa: E402

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

import pygame  # noqa: E402


class FakeDisplayBackend:
    """Display stub that captures every frame pushed via update() into a list."""

    def __init__(self, width: int = 320, height: int = 240) -> None:
        self.width = width
        self.height = height
        self.frames: list[Image.Image] = []
        self._surface: pygame.Surface = pygame.Surface((width, height))
        self._has_splash = False

    @property
    def surface(self) -> pygame.Surface:
        return self._surface

    @property
    def has_system_splash(self) -> bool:
        return self._has_splash

    def init(self) -> None:
        self._has_splash = True

    def update(self, surface: pygame.Surface, rects: list[Box] | None = None) -> None:
        rgb = pygame.image.tostring(surface, "RGB")
        img = Image.frombytes("RGB", (self.width, self.height), rgb)
        self.frames.append(img)

    def transfer_ms(self, rect: Box | None = None) -> float:
        return 0.0


# Backwards-compatible alias used by widget tests.
FakeLcd = FakeDisplayBackend


# ---------------------------------------------------------------------------
# FakeEncoder + FakeInputBackend — injectable input events for tests
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


class FakeInputBackend:
    """Input backend backed by FakeEncoder, with click injection."""

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
# FakeDataBackend — configurable per-domain items and package installs
# ---------------------------------------------------------------------------


class FakeDataBackend(DataBackend):
    """Data backend that returns configured items and records installs."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, list[Item]]] = {}
        self._updates: dict[str, list[PackageUpdate]] = {}
        self._installed: list[list[str]] = []
        self._install_success: bool = True
        self._install_progress: list[tuple[str, float, str, bool]] = []
        self._domain_summaries: dict[str, dict[str, str]] = {}

    def set_items(self, mode: str, domain: str, items: list[Item]) -> None:
        self._items.setdefault(mode, {})[domain] = items

    def set_updates(self, domain: str, updates: list[PackageUpdate]) -> None:
        self._updates[domain] = updates

    def set_domain_summary(self, mode: str, domain: str, summary: str) -> None:
        self._domain_summaries.setdefault(mode, {})[domain] = summary

    def domains(self, mode: str = "") -> tuple[tuple[str, str], ...]:
        all_domains: tuple[tuple[str, str], ...] = (
            ("pedalboards", "Pedalboards"),
            ("plugins", "Plugins"),
            ("config", "Config"),
            ("system", "System"),
        )
        if mode == "updates":
            return (("system", "System"),)
        return all_domains

    def domain_items(self, mode: str, domain: str) -> list[Item]:
        if mode == "updates":
            return [
                Item(
                    u.name,
                    f"{u.name} {u.old_version}",
                    False,
                    f"\u2191{u.new_version}",
                    [],
                )
                for u in self._updates.get(domain, [])
            ]
        return list(self._items.get(mode, {}).get(domain, []))

    def domain_summary(self, mode: str, domain: str) -> str:
        return self._domain_summaries.get(mode, {}).get(domain, "")

    def install_packages(
        self, packages: list[str], progress: Callable[[str, float, str, bool], None]
    ) -> bool:
        self._installed.append(list(packages))
        for entry in self._install_progress:
            progress(*entry)
        # Remove installed packages from update lists so the refresh hides them,
        # mirroring real backend behavior.
        for domain, updates in self._updates.items():
            self._updates[domain] = [u for u in updates if u.name not in packages]
        return self._install_success


# ---------------------------------------------------------------------------
# FakeServiceBackend — stub lifecycle and crash info
# ---------------------------------------------------------------------------


class FakeServiceBackend:
    """Service backend that records calls instead of touching systemd."""

    def __init__(
        self,
        boot_mode: BootMode = BootMode.USER_RECOVERY,
        sha: str = "abc1234",
        restart_diagnosis: CrashInfo | None = None,
        crash_info_override: CrashInfo | None = None,
    ) -> None:
        self.boot_mode = boot_mode
        self.sha = sha
        self.calls: list[str] = []
        self.restart_diagnosis: CrashInfo | None = restart_diagnosis
        self._crash_info_override: CrashInfo | None = crash_info_override

    def stop_main_app(self) -> bool:
        self.calls.append("stop_main_app")
        return True

    def start_main_app(self) -> bool:
        self.calls.append("start_main_app")
        return True

    def restart_jack(self) -> bool:
        self.calls.append("restart_jack")
        time.sleep(0.05)
        return True

    def restart_mod(self) -> bool:
        self.calls.append("restart_mod")
        time.sleep(0.05)
        return True

    def diagnose_services(self, services: list[str]) -> CrashInfo:
        self.calls.append(f"diagnose_services:{','.join(services)}")
        if self.restart_diagnosis is not None:
            return self.restart_diagnosis
        return CrashInfo(
            boot_mode=BootMode.USER_RECOVERY,
            failed_service=None,
            crash_log="",
            service_states={s: "active" for s in services},
        )

    def reboot(self) -> None:
        self.calls.append("reboot")

    def power_off(self) -> None:
        self.calls.append("power_off")

    def recovery_sha(self) -> str:
        return self.sha

    def crash_info(self) -> CrashInfo | None:
        if self._crash_info_override is not None:
            return self._crash_info_override
        if self.boot_mode != BootMode.CRASH_RECOVERY:
            return None
        return CrashInfo(
            boot_mode=BootMode.CRASH_RECOVERY,
            failed_service="mod-host",
            crash_log="boom",
            service_states={},
        )


# ---------------------------------------------------------------------------
# RecoveryApp test harness — drives the core with fake backends
# ---------------------------------------------------------------------------


class AppHarness:
    """Wraps a RecoveryAppCore with event injection and frame capture."""

    def __init__(self, app: RecoveryAppCore, display: DisplayBackend) -> None:
        self.app = app
        self.display = display

    def inject(self, *events: InputEvent) -> None:
        """Feed events into the app and redraw if dirty."""
        for ev in events:
            self.app.handle_event(ev)
        if self.app._lcd_needs_update:
            self.app.draw_current_screen()
            self.app._backends.display.update(self.app.surface)
        self.app._lcd_needs_update = False
        self.app._pending_lcd_clip = None
        self.app._inline_rects = []

    def drain(self, timeout: float = 3.0) -> None:
        """Wait for any in-progress background work to finish.

        Polls until the current menu screen leaves PROGRESS state (meaning the
        background thread called clear_progress), then does a final redraw.
        """
        from pistomp_recovery.ui.screens.menu_screen import MenuScreen

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            screen = self.app.current_screen()
            if not isinstance(screen, MenuScreen) or screen._state != "PROGRESS":
                break
            time.sleep(0.05)
        self.inject()

    def redraw(self) -> None:
        """Force a draw + frame capture (e.g. after a programmatic state change)."""
        self.app.draw_current_screen()
        self.app._backends.display.update(self.app.surface)
        self.app._lcd_needs_update = False
        self.app._pending_lcd_clip = None
        self.app._inline_rects = []

    def scroll_to(self, label: str) -> None:
        """Rotate selection until a target whose label contains ``label``."""
        menu = self._menu()
        if menu is None:
            return
        for _ in range(len(menu._nav) * 2):
            target = menu._target_at(menu._nav[menu._sel])
            if label in target.label:
                return
            self.inject(InputEvent.RIGHT)
        raise RuntimeError(f"Could not find target: {label}")

    def select(self, label: str) -> None:
        """Scroll to and click a target."""
        self.scroll_to(label)
        self.inject(InputEvent.CLICK)

    def long_press(self) -> None:
        self.inject(InputEvent.LONG_CLICK)

    def nav_labels(self) -> list[str]:
        """Labels of every navigable target on the current screen."""
        menu = self._menu()
        if menu is None:
            return []
        return [menu._target_at(pos).label for pos in menu._nav]

    def row_labels(self) -> list[str]:
        """Labels of every target across all rows (incl. disabled)."""
        menu = self._menu()
        if menu is None:
            return []
        return [t.label for row in menu._rows for t in row.targets]

    def _menu(self) -> "MS | None":
        screen = self.app.current_screen()
        if isinstance(screen, MS):
            return screen
        return None


@pytest.fixture
def fake_encoder() -> FakeEncoder:
    return FakeEncoder()


@pytest.fixture
def fake_input(fake_encoder: FakeEncoder) -> FakeInputBackend:
    return FakeInputBackend(fake_encoder)


@pytest.fixture
def _fake_display() -> FakeDisplayBackend:
    return FakeDisplayBackend()


@pytest.fixture
def fake_display(_fake_display: FakeDisplayBackend) -> FakeDisplayBackend:
    return _fake_display


# Backwards-compatible alias for widget tests that import `fake_lcd`.
@pytest.fixture
def fake_lcd(_fake_display: FakeDisplayBackend) -> FakeDisplayBackend:
    return _fake_display


@pytest.fixture
def fake_data() -> FakeDataBackend:
    return FakeDataBackend()


@pytest.fixture
def fake_services() -> FakeServiceBackend:
    return FakeServiceBackend()


@pytest.fixture
def recovery_app(
    fake_display: FakeDisplayBackend,
    fake_input: FakeInputBackend,
    fake_data: FakeDataBackend,
    fake_services: FakeServiceBackend,
) -> Generator[AppHarness, None, None]:
    """Construct a RecoveryAppCore with fake backends, initialized and ready."""
    app = RecoveryAppCore(
        AppBackends(
            display=fake_display,
            input=fake_input,
            data=fake_data,
            services=fake_services,
        ),
        CrashInfo(
            boot_mode=fake_services.boot_mode,
            failed_service=None,
            crash_log="",
            service_states={},
        ),
    )
    app.init()
    harness = AppHarness(app, fake_display)
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
    request: pytest.FixtureRequest,
    fake_display: FakeDisplayBackend,
    snapshot_update: bool,
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
            fake_display.frames[-1],
            f"{module}/{test}/{suffix}",
            update=snapshot_update,
        )

    return _assert
