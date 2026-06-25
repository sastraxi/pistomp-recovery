# pi-Stomp Recovery Development Guide

## Concepts

`pistomp-recovery` is the package-update and recovery service for pi-Stomp. It takes over the LCD when the main app can't run — either because pi-Stomp crashed in a loop, or because the user picked "Recovery" from the System Menu — and offers a small menu to restart services, roll state back to a known-good checkpoint or to factory, apply package updates, and reboot/power off.

It is deliberately a **black box around the device**. The UI core (`RecoveryAppCore`) owns nothing but the LCD menu flow and a screen stack; every side effect — drawing pixels, reading the encoder, listing rollback targets, restarting systemd units — is delegated to an injected backend. On the real device those backends talk to SPI/GPIO, git, the system package manager (`pacman` on Arch, `apt`/`dpkg` on Debian), and systemd; in the emulator they talk to a pygame window, the keyboard, and in-memory stubs. The same core runs in both.

Recovery and the main app are mutually exclusive owners of the LCD. The systemd unit declares `Conflicts=mod-ala-pi-stomp.service`, so starting recovery stops pi-Stomp and resuming pi-Stomp stops recovery — only one process drives the screen at a time.

This service lives in an ecosystem of sibling repos:

| Repo | Role |
|------|------|
| `../pi-gen-pistomp` | Builds the Debian (Raspberry Pi OS Trixie) OS image. Owns the `.deb` packaging under `debpkgs/pistomp-recovery/` (the service file lives there too), the image-build factory-ref seeding, and the OTA apt-repo tooling. Only currently exercised deployment target. |
| `../pi-stomp` | The main app (Python). Owns the LCD/encoders/pedalboards in normal operation. `mod-ala-pi-stomp.service` conflicts with ours. |
| `../mod-ui` | Web UI (Tornado) that talks to mod-host over TCP. |

> When a change could live in either repo, prefer making it here and keep `../pi-stomp` edits minimal.
>
> **Packaging lives in `../pi-gen-pistomp`.** This repo intentionally has no `PKGBUILD`, `.deb` `debian/` tree, or service file anymore — it is deployment-agnostic source. The only deployment target we exercise today is Debian via `pi-gen-pistomp`; `PacmanManager` remains for Arch as a runtime code path, but nothing in-repo builds an Arch package.

## OS & Deployment

Recovery runs on a custom Linux image (currently Debian Trixie via `pi-gen-pistomp`; `pacman`-based Arch is still supported at runtime by the package-manager abstraction), out of its own venv, as the `pistomp` user (not root).

| Path | Purpose |
|------|---------|
| `/opt/pistomp/venvs/pistomp-recovery/` | Python venv (`--system-site-packages`), built by the `.deb` packaging |
| `…/venvs/pistomp-recovery/lib/python3.X/site-packages/pistomp_recovery/` | The installed package (a plain copy, **not** editable) |
| `/usr/lib/systemd/system/pistomp-recovery.service` | Service unit (`Conflicts=mod-ala-pi-stomp`); source of truth is `../pi-gen-pistomp/debpkgs/pistomp-recovery/debian/pistomp-recovery.pistomp-recovery.service` |
| `/home/pistomp/data/config/` | Live config files the `config` facet versions |
| `/home/pistomp/data/.pedalboards/` | Pedalboard bundles the `pedalboards` facet versions; `git config pistomp.factory-ref` is set here at image-build time |
| `/home/pistomp/.pistomp-recovery/` | Recovery's git repos + `packages.stamp` |
| `/run/lcd.init` | Stamp left by the boot splash so recovery skips LCD reset |

```bash
ssh pistomp@pistomp.local
sudo systemctl start pistomp-recovery      # take over the LCD (stops pi-Stomp via Conflicts=)
sudo systemctl restart pistomp-recovery    # reload after a code change
sudo journalctl -u pistomp-recovery -f     # live logs
sudo systemctl start mod-ala-pi-stomp      # hand the LCD back to pi-Stomp
```

The device hostname/user default to `pistomp@pistomp.local` (override with `PISTOMP_HOST` / `PISTOMP_USER`).

### Pushing changes to the device

**1. Surgical rsync (fast dev iteration).** Because the package is installed as a plain copy in site-packages, you can rsync source straight over it. This is the quickest loop and what we use while debugging hardware:

```bash
rsync -az --delete --exclude='__pycache__' --exclude='*.pyc' \
  src/pistomp_recovery/ \
  pistomp@pistomp.local:/opt/pistomp/venvs/pistomp-recovery/lib/python3.13/site-packages/pistomp_recovery/
ssh pistomp@pistomp.local 'sudo systemctl restart pistomp-recovery'
```

(Match `python3.13` to the device's system Python.) Caveats: this only updates `.py` files — a **new dependency** in `pyproject.toml` is *not* installed this way (verify it's already importable in the venv, e.g. via `--system-site-packages`, or do a full build). The service file and `.deb` metadata aren't covered either. And it's a throwaway: the next `apt upgrade` or package rebuild overwrites it.

**2. Build + install the `.deb` (proper).** Packaging is owned by `../pi-gen-pistomp` — see that repo's `debpkgs/pistomp-recovery/build.sh`, `scripts/fetch-packages.sh`, and `docs/OTA.md` for the full pipeline (`dpkg-buildpackage` → cache → image install, plus the GitHub Pages apt-repo for OTA). Run the build from `pi-gen-pistomp`; don't replicate it here.

## Tests

```bash
uv sync --group dev               # install dev deps
uv run pytest                     # all tests (conftest sets SDL_VIDEODRIVER=dummy)
uv run pytest --snapshot-update   # accept changed LCD widget snapshots
uv run ruff check src/            # lint
uv run pyright src/               # type check — zero errors required (strict)
uv run pistomp-recovery-emulator  # interactive pygame window, keyboard nav
```

Widget snapshot tests render to a pygame Surface → `FakeLcd` converts to a PIL image → byte-for-byte `.tobytes()` comparison against `tests/snapshots/`. Regenerate baselines with `--snapshot-update` after intentional UI changes.

Two test layers worth knowing:

- **Widget/screen snapshots** (`test_widgets.py`, `test_screens.py`) drive the core with `FakeDisplayBackend` + `FakeInputBackend` and assert pixels or navigation.
- **Saga tests** (`test_emulator_saga.py`) wire the *real* facets (`FileFacet`, `PedalboardFacet`) against temp directories through `EmulatorDataBackend`, so a confirm-and-rollback actually mutates files and stamps end-to-end.

Strict typing applies to `src/` (the gate is `pyright src/`). Test files relax `reportPrivateUsage` via a file-top `# pyright:` comment because they legitimately reach into app internals.

### Emulator controls

`←`/`→` navigate reticules (including the header back/exit icon), `Enter`/`Space` select, `Esc` quits. `--force-crash` starts in crash recovery mode; `--force-menu` (real entry point) forces the menu. Long-press is **not** a back affordance — navigate to the header `←`/`►` icon.

## Architecture

The single mental model: **`RecoveryAppCore` (`app.py`) is UI-only and depends on nothing but `AppBackends`** — a frozen container of four protocols (`backends.py`). The two entry points inject different implementations, so the same UI runs on the device and in the emulator.

| Protocol | Real (`backends_real.py`) | Emulator (`emulator/backends.py`) |
|----------|---------------------------|-----------------------------------|
| `DisplayBackend` | SPI ILI9341 | pygame window |
| `InputBackend` | encoder + ADC switch | keyboard |
| `DataBackend` | git/package-manager facets | facets on temp dirs |
| `ServiceBackend` | systemd | stubs |

`run()` is a 30ms loop: poll input → route to the top screen → redraw + flush if dirty. (`pre_poll`/`post_draw` hooks let the emulator pump its window without the core knowing one exists.)

**Crash loop.** This service exists because of one systemd chain, which is worth knowing since it isn't visible from the Python: `mod-ala-pi-stomp.service` has `OnFailure=pistomp-recovery.service` and `StartLimitBurst=3` / `StartLimitIntervalSec=180`, so three crashes in three minutes hand the LCD to recovery. `get_boot_mode()` then reads `systemctl is-failed mod-ala-pi-stomp` to choose `CRASH_RECOVERY` (shows `CrashScreen`) vs `USER_RECOVERY` (main menu). The unit's `Conflicts=mod-ala-pi-stomp` is what guarantees one LCD owner.

**Menus.** There is one screen type, `MenuScreen` (states `LIST | CONFIRM | PROGRESS`); `CrashScreen` subclasses it. You build menus out of `Row`/`Target` (`items.py`) and push them — there is no detail state and no other screen class. Rules that aren't obvious from the types: selection is reverse video so labels carry **no literal brackets**; a `Target.confirm=` string makes `MenuScreen` pop the modal for you; a multi-action item pushes a child menu; capture state in closures, never via callback args.

**Facets** (`facet.py`, `file_facet.py`, `pedalboards.py`) are the recoverable domains — `config`, `system`, `pedalboards`, `packages` — behind a common protocol (`list_items`/`stamp`/`rollback`), registered by `register_default_facets()`. **stamp** = mark current state known-good (pi-Stomp runs `pistomp-stamp` on a good pedalboard load). Two distinct git models:

- **FileFacet** (`config`, `system`): copy-into-repo + copy-back-on-rollback. `factory` branch holds the first snapshot; factory rollback = `git checkout factory -- <file>` then copy repo→live; stamp rollback = `git checkout HEAD -- <file>` then copy repo→live.
- **PedalboardFacet** (`pedalboards`): in-place tracking — the repo IS the live `.pedalboards/` dir. No copy-back step. Factory rollback restores from the **factory ref** (`git config pistomp.factory-ref`, set at image-build time to e.g. `origin/main`; falls back to the `factory` branch for locally-init'd repos); stamp rollback restores from the **last commit that touched the path**. The `factory` branch exists but is unused by rollback.

Both use a `device` working branch. The root menu's Checkpoint/Factory/Updates rows feed one shared picker parameterised by `mode`; package updates are scoped to a domain via `PACKAGE_DOMAIN` in `constants.py`.

**Rendering** is deterministic for byte-for-byte snapshot tests: a 320×240 surface (40×15 grid), one non-antialiased 8×16 bitmap font at one size, emphasis via reverse video only. Always render through `SafeFont`/`get_font()` (never `pygame.font.Font` — it has a circular import on Python 3.14). Widgets are plain `draw(surface)` renderers; there is no widget hierarchy.

**Hardware** (`hardware/`, all `try/except ImportError` so the package imports off-device) must mirror `../pi-stomp` exactly — its implementation is the proven reference, and the `--system-site-packages` venv resolves the same `gpiozero`/`lgpio`/`spidev`. The non-obvious facts: nav encoder is D=GPIO17/CLK=GPIO4 via `gpiozero.Button` (pull-up, gray-code decode) with a claim-retry loop; the push-switch is on the **MCP3008 ADC, bus 0 / CE1, channel 4** (CE0 is the LCD); `lcd.py` drives the panel **landscape-native** (MADCTL `0xE8`/`0x28` set once in `init` via `_madctl_for(flip)`; `flip=True` → `0xE8` mirrors both axes, `flip=False` → `0x28` no mirror — note this is the **inverse** of pi-stomp's `LcdIli9341.flip` flag, preserved to keep the default `LcdSpi()` call site upright on the Tre) and pushes both full and partial rects through a single `_block_fast` path (numpy RGB565 pack → single SPI lock/CS, `os.write` chunked by `SPIDEV_BUFSIZ`) — surface coords map straight to the panel address window, no per-push rotation or coordinate swap.

## Key Files

**Entry & core**
- `__main__.py` — real entry: argparse, boot mode, signal handling, `make_real_backends()`, run loop
- `app.py` — `RecoveryAppCore`: screen stack, poll loop, menu construction, domain picker, refresh
- `backends.py` — the four backend `Protocol`s + `AppBackends` container
- `backends_real.py` — device backends (SPI LCD, GPIO/ADC input, git/apt/pacman data, systemd)

**Facets & domains**
- `facet.py` — `Facet` protocol + registry (`register_default_facets`, `all_facets`)
- `file_facet.py` — `FileFacet`: copy-into-repo + commit/checkout model for config & system
- `pedalboards.py` — `PedalboardFacet`: in-place tracking, factory-ref factory rollback
- `config.py`, `system.py` — `make_*_facet()` factories (which files each tracks)
- `packages/installer.py` — pacman wrapper (download/install/rollback-from-cache)
- `packages/packages.py` — package facet, version tracking, `stamp_packages`
- `packages/health.py` — `systemctl is-active` / journal helpers
- `git_util.py` — git ops: init, commit, factory/device branches, checkout, rollback, `factory_ref()`
- `stamp.py` — `pistomp-stamp` CLI (stamp/status), called by pi-Stomp on good load

**System integration**
- `service.py` — boot mode, crash diagnosis, systemd start/stop/restart, `recovery_sha`
- `constants.py` — paths, LCD dims, `PISTOMP_PACKAGES`, `PACKAGE_SERVICES`/`PACKAGE_DOMAIN`, `domain_for_package`
- `items.py` — `Item`/`Action` (data) + `Row`/`Target` (UI currency)
- `util.py` — `human_time()` relative timestamps

**UI**
- `ui/screens/menu_screen.py` — universal `Header` + `Row` list, states LIST/CONFIRM/PROGRESS
- `ui/screens/crash.py` — `CrashScreen` (service states + log + `[RESUME]|[RECOVERY]`)
- `ui/widgets/header.py`, `confirm_dialog.py`, `text.py` — title bar, modal, ProgressBar/StatusLine
- `ui/fonts/__init__.py` — `SafeFont`, `get_font()`, `cell_size()`, `FONT_SIZE`, `TEXT_DY`
- `ui/colors.py` — `Color`/`ColorName` aliases, softened EGA/QBASIC palette
- `ui/display.py` — pygame Surface ↔ SPI LCD bridge
- `ui/input.py` — `InputManager`: encoder + switch → `InputEvent`
- `pygame_init.py` — idempotent headless-safe pygame + `_freetype` init

**Hardware** (`try/except ImportError`)
- `hardware/encoder.py`, `switch.py`, `lcd.py`

**Emulator**
- `emulator/backends.py` — pygame display, fake input, facets on temp dirs, stub services
- `emulator/bootstrap.py` — `EmulatorApp`, the `pistomp-recovery-emulator` entry point
- `emulator/window.py`, `controls.py`, `lcd_pygame.py` — window event loop, fake encoder/input

**Packaging** — owned by `../pi-gen-pistomp/debpkgs/pistomp-recovery/` (`.deb` build, service unit, changelog). No packaging artifacts live in this repo.

## Design Principles

- **Black box around the device** — the core only knows `AppBackends`; SPI/GPIO/package-manager/systemd live behind protocols, so the emulator and the device run identical UI code.
- **Match pi-Stomp's hardware approach** — the encoder/switch/LCD code mirrors `../pi-stomp` exactly; it's the proven reference, and the shared `--system-site-packages` venv resolves the same GPIO backend.
- **Type safety** — `pyright --typecheckingMode strict`, zero errors in `src/`. No bare `dict`/`list`/`Any`; semantic aliases (`Color`, `SafeFont`, …).
- **Deterministic rendering** — one bitmap font, one size, non-antialiased; emphasis is reverse video. Snapshot-tested byte-for-byte.
- **One screen type** — build `Row`/`Target` lists and reuse `MenuScreen`; push a new menu instead of inventing a screen class.
- **Refresh in place** — after a destructive action, rebuild the current list (and parent badges) rather than navigating away; pop if it became empty.
- **Fail gracefully** — hardware modules degrade when GPIO/SPI libs are missing; data backends log and return empty rather than crashing the loop.

## When editing

- **Adding a recoverable domain?** Implement the `Facet` protocol (or reuse `FileFacet`), register it in `register_default_facets()`, and add it to the `domains()` of both `RealDataBackend` and `EmulatorDataBackend`. Updates are scoped via `PACKAGE_DOMAIN` in `constants.py`.
- **Adding a screen/flow?** Build `Row`/`Target` lists and push a `MenuScreen` (pass a header icon `Target`). Use `Target.confirm=` for anything destructive — `MenuScreen` opens/handles the dialog. Selection is reverse video, so no literal brackets in labels; capture state with closures (`lambda n=name: …`), never via callback args.
- **Adding a widget?** Implement `draw(surface)`, apply `fonts.TEXT_DY` to text blits, add a snapshot test in `tests/test_widgets.py`.
- **Changing a color?** Edit `COLORS` in `ui/colors.py`. Changing the look? Vary reverse video / color, not size or bold.
- **Hardware deps** go in `[project.optional-dependencies] hardware` with `sys_platform == 'linux'` markers; never import outside `try/except ImportError`.
- **New emulator domain?** Add matching stub data in `emulator/backends.py` so the emulator still exercises clean-stamped / dirty-stamped / factory / unknown item states.
- **New runtime dependency?** Declare it in `pyproject.toml`, run `uv lock`, and remember the rsync deploy won't install it — rebuild the package or confirm it's already in the venv.

## Scope

In scope: package updates/rollback, crash-recovery LCD UI, per-domain git versioning (pedalboards, config, system, packages), factory reset, health checks. Out of scope: WiFi config, pedalboard editing, plugin management, audio processing, the web UI.
