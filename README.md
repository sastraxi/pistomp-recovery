pistomp-recovery
==================

Package update and recovery service for pi-Stomp.

Runs as an exclusive LCD service (conflicts with mod-ala-pi-stomp). Activates via:
- systemd OnFailure when the main app crashes 3+ times in 180 seconds
- User selecting "Recovery" from the System Menu

Features
--------

- **Crash recovery** — Shows crash log with Resume/Recovery Menu options
- **Action inbox** — Reset dirty items, update available packages — badge counts on main menu
- **Per-pedalboard operations** — Stamp, rollback, or factory-reset individual pedalboards
- **Per-package operations** — Update, stamp, or rollback individual packages with service restart awareness
- **Factory reset** — Confirm dialog, then resets all facets and reboots
- **Health check pipeline** — JACK → mod-host → mod-ui → pi-stomp after updates, with automatic rollback on failure
- **Human-relative timestamps** — "3h ago", "yesterday", "Jun 3"
- **Navigation stack** — Long-press back, persistent screen state, no per-event recreation

Architecture
------------
- **Facets**: git-backed versioned state (etckeeper model)
  - config: default_config.yml, settings.yml
  - pedalboards: .pedalboards/ git repo with per-subdirectory stamp/rollback
  - packages: package-manager version manifests (apt on Debian, pacman on Arch)
  - system: /boot/config.txt, /etc/jackdrc, ALSA state
- **Items**: PedalboardItem and PackageItem data classes for per-unit operations
- **PACKAGE_SERVICES**: maps packages to dependent services for restart ordering
- **Package management**: distro-agnostic update/rollback with health checks (`apt`/`dpkg` on Debian, `pacman` on Arch)
- **LCD UI**: pygame widget library, 320x240, navigation stack, ConfirmDialog overlay

CLI
---
- `pistomp-recovery` — main service (started by systemd)
- `pistomp-stamp stamp` — stamp all facets as known-good
- `pistomp-stamp status` — show dirty state for all facets

Development
-----------
    uv sync --group dev
    uv run pytest                # Run tests
    uv run pytest --snapshot-update  # Accept changed widget snapshots
    uv run ruff check src/       # Lint
    uv run pyright src/           # Type check (zero errors required)
    uv run pistomp-recovery-emulator  # Interactive pygame window

Emulator controls:
- ←/→ — Navigate menu
- Enter/Space — Select
- L — Long press (back/cancel)
- Esc — Quit
- --force-crash — Start in crash recovery mode

Packaging
---------
This repo is deployment-agnostic source. The `.deb` build, systemd unit, and
OTA apt-repo tooling live in `../pi-gen-pistomp` (see
`debpkgs/pistomp-recovery/` and `docs/OTA.md` there). For fast dev iteration,
rsync `src/pistomp_recovery/` straight over the installed site-packages on the
device — see `CLAUDE.md` for the loop.