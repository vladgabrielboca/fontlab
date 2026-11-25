# Architecture

`fontlab` is a declarative configurator: `~/.config/fontlab/state.toml` declares the desired rendering state, and `fontlab/apply.py` converges every managed output to match it idempotently.

## Core Dataflow (`apply.py`)

```text
~/.config/fontlab/state.toml
        │
        ▼
  state.load() ──▶ Context.detect().effective(state)   (replaces unavailable choices with defaults)
        │
        ├──▶ 1. fonts.install(state)          ──▶ ~/.local/share/fonts/fontlab/<family>/
        │                                         (caches darkened TTFs in ~/.cache/fontlab/builds/)
        ├──▶ 2. fontconfig.render_conf()      ──▶ ~/.config/fontconfig/conf.d/70-fontlab-render.conf
        │       fontconfig.web_conf()         ──▶ ~/.config/fontconfig/conf.d/71-fontlab-web.conf
        │       fc-cache (if fonts or conf changed; notices Omarchy shell restart if fonts changed)
        │
        ├──▶ 3. chromium.apply(state)         ──▶ ~/.config/fontlab/chromium-text.conf
        │                                     ──▶ ~/.config/fontlab/chromium-fonts.conf
        │                                     ──▶ ~/.config/uwsm/env (+ systemd --user LD_PRELOAD)
        │       apps.apply(needs_launcher)    ──▶ ~/.local/share/applications/*.desktop (wrapped)
        │
        ├──▶ 4. vencord.apply(state)          ──▶ ~/.config/{vesktop,Vencord,equibop}/settings/quickCss.css
        │
        ├──▶ 5. desktop.apply_gsettings()     ──▶ GNOME org.gnome.desktop.interface keys
        │
        └──▶ 6. desktop.apply_environment()   ──▶ /etc/environment (only with --system / ! and != "keep")
```

## File Ownership (`fontlab/paths.py`)

Every path `fontlab` reads or writes is centralized on `paths.P` (`Paths(home)`). Tests call `paths.configure(tmp_home)` to isolate everything.

| Category | Path | Notes |
|---|---|---|
| **State** | `~/.config/fontlab/state.toml` | Only source of truth. |
| **Presets** | `~/.config/fontlab/presets/<name>.toml` | Named snapshots (`fontlab preset save/load`). |
| **App overrides** | `~/.config/fontlab/apps.json` | Manual `fontlab apps add/skip` list. |
| **Font sources** | `~/.local/share/fontlab/sources/<pkg>/` | Unmodified packages + `manifest.json`; files `0o444` (hard-linked on install). |
| **Installed fonts** | `~/.local/share/fonts/fontlab/<pkg>/` | Active family folders with `.fontlab-key` marker; swapped atomically via `replace_dir()`. |
| **Fontconfig** | `~/.config/fontconfig/conf.d/70-fontlab-render.conf` | AA, hinting, mono hinting, LCD filter, `small_bold`, Google Sans aliases, icon-font darkening exclusions, `<rejectfont>` globs. |
| **Fontconfig** | `~/.config/fontconfig/conf.d/71-fontlab-web.conf` | `sans-serif`/`system-ui`/Arial/etc. aliases (`inter` or `sf`; absent for `system`). |
| **Chromium** | `~/.config/fontlab/chromium-text.conf` | `CONTRAST=..` / `GAMMA=..`; removed when both equal Chromium's Linux defaults (`0.2` / `1.2`). |
| **Chromium** | `~/.config/fontlab/chromium-fonts.conf` | Private `FONTCONFIG_FILE` for Chromium apps when `web_fonts != "system"` (maps GTK UI font → web font so CSS `system-ui` follows `web_fonts`, and adds Windows font dir + `data/web-windows.conf` for `windows`). |
| **Runtime** | `~/.local/share/fontlab/runtime/` | Installed by `install.sh`: `fontlab-text-shim.so`, `chromium-env.sh`, `fontlab-launch`. |
| **Session env** | `~/.config/uwsm/env` | Single marked block for `session_shim=on`, also synced to `systemctl --user`. |
| **Desktop entries** | `~/.local/share/applications/*.desktop` | Marked with `X-Fontlab-Wrapped=true`; user-owned originals backed up in `~/.local/share/fontlab/desktop-backup/`. |
| **Cache** | `~/.cache/fontlab/builds/` | Cached darkened builds (pruned to `KEEP_BUILDS = 16` most recent). |
| **Cache** | `~/.cache/fontlab/apps.json` | Chromium binary detection cache keyed by `path:size:mtime`. |
| **Cache** | `~/.cache/fontlab/preview/` | Profiles & isolated comparison configs for `fontlab preview`. |
| **System (sudo)** | `/usr/local/bin/<app>` | Launch wrappers for `chromium.APPS` installed by `install.sh`. |
| **System (sudo)** | `/etc/environment` | Only `FREETYPE_PROPERTIES` and `QT_NO_SYNTHESIZED_BOLD` lines touched. |

## How Font Packages & Builders Work

1. **`packages.py`** downloads or imports raw assets into a staging dir, runs `builders/run.py` via `toolchain.py` (which locates a Python with `fontTools`: system, `uv`, or an auto-created venv at `~/.local/share/fontlab/venv`), writes `manifest.json`, sets files `0o444`, and atomically swaps into `~/.local/share/fontlab/sources/<id>/`.
   - `<id>/400/` holds the full stock static family (absent for `jbm`, where the system font is the 400 base).
   - `<id>/<weight>/` (`430`, `450`, `475`, `500`) holds only the instanced `Regular` and `Italic` overrides, stripped of `STAT`/`avar` and stamped with Regular/Italic `name`/`OS/2`/`head` metadata so apps treat them as normal weight `400`.
   - **Important hinting difference across packages**:
     - `Inter 400` keeps TrueType hinting bytecode (`fpgm`, `prep`, `cvt `, `gasp`); instanced `Inter 430–500` have **no** TT bytecode tables.
     - `Adwaita Sans 400–500` have no TT bytecode tables.
     - `Roboto 400–500` keep TT bytecode tables at every weight.
     - `SF Pro 400` is OpenType CFF (`.otf`); instanced `SF Pro 430–500` are TrueType (`.ttf`) without TT bytecode.
     - `JetBrains Mono 430–500` grafts variable glyph outlines onto the user's installed copy (preserving Nerd Font icons) and explicitly strips bytecode (`fpgm`/`prep`/`cvt ` + per-glyph programs).
2. **`fonts.py`** computes a `FontSet` per family in `FAMILIES`. When `darkening > 0` on a TrueType UI family (`inter`, `adwaita`, `roboto`; `googlesans` stays stock so it matches Google's web font), `realize()` runs `builders/darken.py` (`FT_Outline_EmboldenXY` with `DARKEN_X_EM = 0.0121 * darkening`, `DARKEN_Y_EM = 0.0121 * 1.25 * darkening`) into `~/.cache/fontlab/builds/<family>-<key>/`.
3. **`fonts.install()`** hard-links files into a staging dir, atomically replaces `~/.local/share/fonts/fontlab/<family>`, and calls `newer_than()` to bump mtime past the current whole second so `fc-cache` never skips a rapid back-to-back apply.

## How the Chromium Text Shim Works (`chromium/`)

Chromium only accepts `--text-contrast` and `--text-gamma` as command-line switches and does **not** forward them to renderer processes.

- **Three entry routes** load `fontlab-text-shim.so` and export `FONTCONFIG_FILE`:
  1. `/usr/local/bin/<browser>` wrappers (`wrapper.sh` → `chromium-env.sh`) for terminal launches and launchers whose `Exec=` resolves through `PATH`.
  2. `fontlab-launch` prepended to Chromium/Electron `.desktop` entries in `~/.local/share/applications/` (`apps.py`, skipping apps already covered by a `/usr/local/bin` wrapper so tools like `omarchy-launch-browser` still see the browser name first).
  3. Optional `session_shim=on` (`LD_PRELOAD` in `~/.config/uwsm/env` + `systemd --user`) for apps started via WM keybinds or AppImages.
- **Inside `chromium/text-shim.c`**:
  - `shim_init()` (constructor) resolves libc symbols eagerly, checks whether `/proc/self/exe`'s directory contains `icudtl.dat` + (`resources.pak` or `v8_context_snapshot.bin`), reads `FONTLAB_TEXT_CONF` (or `~/.config/fontlab/chromium-text.conf`), sets `FONTCONFIG_FILE` if unset and `~/.config/fontlab/chromium-fonts.conf` exists, and strips `fontlab-text-shim.so` from `LD_PRELOAD`.
  - **Zygote path**: hooks `sendmsg()`, detects base::Pickle `"renderer"` fork messages, and splices `--text-contrast=...` and `--text-gamma=...` into the serialized argv.
  - **No-zygote path**: hooks `execve`/`execv`/`execvp`/`execvpe`/`posix_spawn`, detects `--type=renderer`, and appends the flags on a stack buffer (no heap allocation after `fork()`).

## Isolated Preview & Comparison (`fontlab/preview.py`)

`compare_setup(state)` builds a completely self-contained fontconfig tree + symlinked font directory + `chromium-text.conf` under `~/.cache/fontlab/preview/compare/` (hiding `~/.local/share/fonts/fontlab` via `<rejectfont>`) and launches `/usr/bin/chromium` directly (bypassing `/usr/local/bin/chromium`). This is the exact pattern used for isolated headless benchmarks (see `.agents/skills/render-benchmark/SKILL.md`).
