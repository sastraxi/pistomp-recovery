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
PLUGINS_STAMP_FILE: str = f"{RECOVERY_DIR}/plugins.stamp"
FACTORY_PACKAGES_FILE: str = "/etc/pistomp/factory-packages.list"
FACTORY_LV2_BUNDLES_FILE: str = "/etc/pistomp/factory-lv2-bundles.list"
LCD_WIDTH: int = 320
LCD_HEIGHT: int = 240

FACTORY_BRANCH: str = "factory"
DEVICE_BRANCH: str = "device"

FACET_NAMES: tuple[str, ...] = ("config", "pedalboards", "plugins", "packages", "boot")

# apt Release file `Origin:` / `Label:` value for the pi-gen-pistomp custom repo.
# Used by AptManager.discover_packages() to identify which installed packages
# came from the pistomp repo (rather than Debian/Raspbian base).
PISTOMP_APT_ORIGIN: str = "pistomp"

# pacman repo name for the pi-gen-pistomp custom packages (Arch path).
PISTOMP_PACMAN_REPO: str = "pistomp"

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
    DOMAIN_PLUGINS: ("plugins",),
    DOMAIN_CONFIG: ("config", "boot"),
    DOMAIN_SYSTEM: ("packages",),
}

def domain_for_package(pkg: str) -> str:
    return DOMAIN_SYSTEM


# Maps each package to the services that must be restarted after it is updated.
# Packages not listed here default to no restarts (conservative non-disruptive).
# Dict order determines the restart sequence (jack → mod-host → … → browsepy);
# pistomp_services() derives the full ordered service list from these values.
PACKAGE_SERVICES: dict[str, list[str]] = {
    "jack2-pistomp": ["jack", "mod-host", "mod-ui", "mod-ala-pi-stomp"],
    "mod-host-pistomp": ["mod-host", "mod-ui", "mod-ala-pi-stomp"],
    "mod-ui": ["mod-ui"],
    "pi-stomp": ["mod-ala-pi-stomp"],
    "mod-midi-merger": ["mod-host"],
    "mod-ttymidi": ["mod-host"],
    "amidithru": ["mod-amidithru"],
    "fluidsynth-headless": ["jack"],
    "sfizz-pistomp": ["jack"],
    "jack-capture": ["jack"],
    "hylia": ["jack"],
    "browsepy": ["browsepy"],
    "touchosc2midi": ["mod-touchosc2midi"],
}


def pistomp_services() -> list[str]:
    """All pi-stomp systemd services in restart order, derived from PACKAGE_SERVICES."""
    seen: list[str] = []
    for svcs in PACKAGE_SERVICES.values():
        for s in svcs:
            if s not in seen:
                seen.append(s)
    return seen


def services_for_packages(packages: list[str]) -> list[str]:
    chain = pistomp_services()
    seen: set[str] = set()
    extras: list[str] = []
    for pkg in packages:
        for svc in PACKAGE_SERVICES.get(pkg, []):
            if svc not in seen:
                seen.add(svc)
                if svc not in chain:
                    extras.append(svc)
    return [svc for svc in chain if svc in seen] + extras
