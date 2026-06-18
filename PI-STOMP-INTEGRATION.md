# pi-stomp stamping integration (Phase 6)

**Status:** Ready to implement. This document describes the changes needed in `../pi-stomp`.

## Changes required

### 1. `modalapi/mod.py` — call `pistomp-stamp` after successful pedalboard load

In `pedalboard_change()`, after the POST to `pedalboard/load_bundle/` succeeds and `set_current_pedalboard()` is called:

```python
import subprocess
subprocess.run(["pistomp-stamp", "stamp"], check=False)
```

Insert at line 839 in `modalapi/mod.py`, after `self.bot_encoder_mode = BotEncoderMode.DEFAULT`:

```python
# After set_current_pedalboard()
self.set_current_pedalboard(self.pedalboard_list[self.selected_pedalboard_index])
self.bot_encoder_mode = BotEncoderMode.DEFAULT
# NEW:
try:
    subprocess.run(["pistomp-stamp", "stamp"], check=False)
except Exception:
    logging.debug("pistomp-stamp failed", exc_info=True)
```

### 2. Add `pistomp-recovery` as a dependency

In `pi-stomp`'s PKGBUILD, add `pistomp-recovery` to `depends` (or at least ensure `pistomp-stamp` is on `PATH`). Since `pistomp-recovery` is already installed on the image, this is just ensuring the dependency chain is explicit.

### 3. `pistomp/settings.py` — no symlink awareness needed

The recovery system uses a **copy + hash** model: config files stay at their normal paths (`/home/pistomp/data/config/settings.yml`, `/home/pistomp/data/config/default_config.yml`) and are copied into `~/.pistomp-recovery/config.git/` when stamped or initialized.

`pistomp/settings.py` can keep writing to `DATA_DIR/settings.yml` exactly as it does today. There is no symlink to accidentally replace, and normal file writes/creates work without any code changes.

### 4. Factory reset deletes `settings.yml` when absent from factory

`pistomp-recovery` copies files into its repos on first use and on stamp. The factory branch captures the initial state. If `settings.yml` did not exist when the factory snapshot was taken, rolling back to factory must delete `/home/pistomp/data/config/settings.yml` rather than leaving a stale file in place.

Ensure any pi-stomp-level "settings reload" path re-reads the file and treats a missing file as an empty settings dict.

## Rationale

- Stamping is **pi-stomp's job** because only pi-stomp knows the system is working (JACK → mod-host → mod-ui → pi-stomp all up).
- Recovery should **not** stamp on the user's behalf — the whole point of a stamp is "I know this works."
- Recovery's role is purely rollback + install + resume. Health validation happens by pi-stomp successfully starting.
- Config files (`default_config.yml`, `settings.yml`) are first-class recovery facets and must be restored cleanly on factory reset, including the case where the factory state is "file does not exist."
- The **copy + hash** model avoids symlink/FAT32 complications: live files stay in place, the repo stores committed snapshots, and rollback is a straightforward file copy.
