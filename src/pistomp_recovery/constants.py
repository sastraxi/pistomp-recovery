from __future__ import annotations

INIT_STAMP: str = "/run/lcd.init"
PISTOMP_USER: str = "pistomp"
PISTOMP_HOME: str = "/home/pistomp"
DATA_DIR: str = f"{PISTOMP_HOME}/data"
CONFIG_DIR: str = f"{DATA_DIR}/config"
PEDALBOARDS_DIR: str = f"{DATA_DIR}/.pedalboards"
# User LV2 plugins installed by mod-ui's PatchStorage downloader. Must match
# mod-ui's LV2_PLUGIN_DIR (defaults to ~/.lv2). Factory plugins ship in the
# system LV2 path and are NOT under here, so anything in this dir is user
# content that factory-reset may remove.
PLUGINS_DIR: str = f"{DATA_DIR}/.lv2"
# Marker file mod-ui writes into every bundle it installs from PatchStorage
# (see mod-ui utils/patchstorage.cpp). Its presence is how recovery tells a
# user-installed plugin apart from a factory one.
PATCHSTORAGE_MARKER: str = "patchstorage.json"
# Soft warning threshold for the plugins cache. Recovery only surfaces this as
# a warning; it does NOT auto-evict. Enforcement (refusing/pruning installs)
# belongs in mod-ui's PatchStorage installer, which owns plugin delivery.
PLUGINS_CACHE_WARN_BYTES: int = 512 * 1024 * 1024
RECOVERY_DIR: str = f"{PISTOMP_HOME}/.pistomp-recovery"
PACKAGES_STAMP_FILE: str = f"{RECOVERY_DIR}/packages.stamp"
FACTORY_PACKAGES_FILE: str = "/etc/pistomp/factory-packages.list"
LCD_WIDTH: int = 320
LCD_HEIGHT: int = 240

FACTORY_BRANCH: str = "factory"
DEVICE_BRANCH: str = "device"

FACET_NAMES: tuple[str, ...] = ("config", "pedalboards", "plugins", "packages", "boot")

PISTOMP_PACKAGES: tuple[str, ...] = (
    "jack2-pistomp",
    "mod-host-pistomp",
    "mod-midi-merger",
    "mod-ttymidi",
    "amidithru",
    "fluidsynth-headless",
    "libfluidsynth2-compat",
    "lcd-splash",
    "sfizz-pistomp",
    "jack-capture",
    "hylia",
    "pi-stomp",
    "mod-ui",
    "pistomp-recovery",
    "jackbridge",
    "browsepy",
    "ffmpeg-pistomp",
    "touchosc2midi",
    "lg",
)

# Debian package names mirror the Arch names — they're all custom packages in
# a custom apt repo, so naming is up to the pi-gen-pistomp build. Adjust here
# once the .deb names are finalised.
PISTOMP_PACKAGES_DEBIAN: tuple[str, ...] = PISTOMP_PACKAGES

# Which recovery domain each package's updates belong to. The four recovery
# domains are pedalboards / plugins / config / system; all currently-tracked
# packages are OS/audio infrastructure, so they map to "system". Per-domain
# plugin/config packages can be reassigned here without touching the UI.
DOMAIN_PEDALBOARDS: str = "pedalboards"
DOMAIN_PLUGINS: str = "plugins"
DOMAIN_CONFIG: str = "config"
DOMAIN_SYSTEM: str = "system"

# Maps each UI domain to the ordered list of facets that back it.
# This is the single source of truth used by all backends (real, emulator).
DOMAIN_FACETS: dict[str, tuple[str, ...]] = {
    DOMAIN_PEDALBOARDS: ("pedalboards",),
    DOMAIN_PLUGINS:     ("plugins",),
    DOMAIN_CONFIG:      ("config", "boot"),
    DOMAIN_SYSTEM:      ("packages",),
}

PACKAGE_DOMAIN: dict[str, str] = {pkg: DOMAIN_SYSTEM for pkg in PISTOMP_PACKAGES}


def domain_for_package(pkg: str) -> str:
    return PACKAGE_DOMAIN.get(pkg, DOMAIN_SYSTEM)


PISTOMP_SERVICES: tuple[str, ...] = (
    "jack",
    "mod-host",
    "mod-ui",
    "mod-ala-pi-stomp",
    "mod-amidithru",
    "browsepy",
)

PACKAGE_SERVICES: dict[str, list[str]] = {
    "jack2-pistomp": ["jack", "mod-host", "mod-ui", "mod-ala-pi-stomp"],
    "mod-host-pistomp": ["mod-host", "mod-ui", "mod-ala-pi-stomp"],
    "mod-ui": ["mod-ui"],
    "pi-stomp": ["mod-ala-pi-stomp"],
    "pistomp-recovery": [],
    "mod-midi-merger": ["mod-host"],
    "mod-ttymidi": ["mod-host"],
    "amidithru": ["jack"],
    "fluidsynth-headless": ["jack"],
    "libfluidsynth2-compat": [],
    "lcd-splash": [],
    "sfizz-pistomp": ["jack"],
    "jack-capture": ["jack"],
    "hylia": ["jack"],
    "jackbridge": [],
    "browsepy": ["browsepy"],
    "ffmpeg-pistomp": [],
    "touchosc2midi": ["mod-touchosc2midi"],
    "lg": [],
}


PACKAGE_SERVICES_DEBIAN: dict[str, list[str]] = PACKAGE_SERVICES


def services_for_packages(packages: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    chain: list[str] = list(PISTOMP_SERVICES)
    for pkg in packages:
        svcs: list[str] = PACKAGE_SERVICES.get(pkg, chain)
        for svc in svcs:
            if svc not in seen:
                seen.add(svc)
                result.append(svc)
    ordered: list[str] = [svc for svc in chain if svc in seen]
    return ordered
