# Architecture

`fontlab` reads `~/.config/fontlab/state.toml` and updates every managed output from `fontlab/apply.py`. Running `apply()` twice with the same state makes no changes on the second pass.

## How `apply()` works

```text
~/.config/fontlab/state.toml
        │
        ▼
  state.load() ──▶ Context.detect().effective(state)   (falls back to defaults for unavailable choices)
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

## Paths (`fontlab/paths.py`)

Every path `fontlab` reads or writes lives on `paths.P` (`Paths(home)`). Unit tests call `paths.configure(tmp_home)` to redirect all reads and writes into a temp directory.

| Category | Path | Notes |
|---|---|---|
| State | `~/.config/fontlab/state.toml` | Only source of truth. |
| Presets | `~/.config/fontlab/presets/<name>.toml` | Named snapshots (`fontlab preset save/load`). |
| App overrides | `~/.config/fontlab/apps.json` | Manual `fontlab apps add/skip` list. |
| Font sources | `~/.local/share/fontlab/sources/<pkg>/` | Unmodified packages and `manifest.json`; files `0o444` (hard-linked on install). |
| Installed fonts | `~/.local/share/fonts/fontlab/<pkg>/` | Active family folders with `.fontlab-key` marker; swapped atomically via `replace_dir()`. |
| Fontconfig | `~/.config/fontconfig/conf.d/70-fontlab-render.conf` | AA, hinting, mono hinting, LCD filter, `small_bold`, Google Sans aliases, icon-font darkening exclusions, `<rejectfont>` globs. |
| Fontconfig | `~/.config/fontconfig/conf.d/71-fontlab-web.conf` | `sans-serif`/`system-ui`/Arial aliases (`inter` or `sf`; absent for `system`). |
| Chromium | `~/.config/fontlab/chromium-text.conf` | `CONTRAST=..` and `GAMMA=..`; removed when both match Chromium's Linux defaults (`0.2` / `1.2`). |
| Chromium | `~/.config/fontlab/chromium-fonts.conf` | Private `FONTCONFIG_FILE` for Chromium apps when `web_fonts != "system"`. Maps the GTK UI font to the chosen web font so CSS `system-ui` follows `web_fonts`, and adds the Windows font dir plus `data/web-windows.conf` when `web_fonts=windows`. |
| Runtime | `~/.local/share/fontlab/runtime/` | Installed by `install.sh`: `fontlab-text-shim.so`, `chromium-env.sh`, `fontlab-launch`. |
| Session env | `~/.config/uwsm/env` | Single marked block for `session_shim=on`, also synced to `systemctl --user`. |
| Desktop entries | `~/.local/share/applications/*.desktop` | Marked with `X-Fontlab-Wrapped=true`; user-owned originals backed up in `~/.local/share/fontlab/desktop-backup/`. |
| Cache | `~/.cache/fontlab/builds/` | Cached darkened builds (pruned to `KEEP_BUILDS = 16` most recent). |
| Cache | `~/.cache/fontlab/apps.json` | Chromium binary detection cache keyed by `path:size:mtime`. |
| Cache | `~/.cache/fontlab/preview/` | Profiles and isolated comparison configs for `fontlab preview`. |
| System (sudo) | `/usr/local/bin/<app>` | Launch wrappers for `chromium.APPS` installed by `install.sh`. |
| System (sudo) | `/etc/environment` | Only `FREETYPE_PROPERTIES` and `QT_NO_SYNTHESIZED_BOLD` lines touched. |

## Font packages and builders

1. `packages.py` downloads or imports raw files into a staging directory, runs `builders/run.py` through `toolchain.py` (which finds a Python with `fontTools`: system, `uv`, or a venv created at `~/.local/share/fontlab/venv`), writes `manifest.json`, sets files `0o444`, and swaps the directory into `~/.local/share/fontlab/sources/<id>/`.
   - `<id>/400/` holds the stock static family (omitted for `jbm`, where the system font serves as the 400 base).
   - `<id>/<weight>/` (`430`, `450`, `475`, `500`) holds only instanced `Regular` and `Italic` overrides, with `STAT`/`avar` removed and `name`/`OS/2`/`head` stamped as Regular/Italic so apps treat them as weight `400`.
   - TrueType hinting bytecode differs by package:
     - `Inter 400` keeps TT bytecode (`fpgm`, `prep`, `cvt `, `gasp`); instanced `Inter 430–500` have none.
     - `Adwaita Sans 400–500` have no TT bytecode.
     - `Roboto 400–500` keep TT bytecode at every weight.
     - `Ubuntu Sans` and `Ubuntu Sans Mono 400–500` are instanced from Canonical's variable fonts (`static-family` builder) and carry only `prep`/`gasp`, no glyph bytecode, like the variable fonts Ubuntu itself installs.
     - `SF Pro 400` is OpenType CFF (`.otf`); instanced `SF Pro 430–500` are TrueType (`.ttf`) without TT bytecode.
     - `JetBrains Mono 430–500` graft variable glyph outlines onto the user's installed copy (keeping Nerd Font icons) and strip bytecode (`fpgm`/`prep`/`cvt ` plus per-glyph programs).
2. `fonts.py` plans a `FontSet` per family in `FAMILIES`. When `darkening > 0` on a TrueType UI family (`inter`, `adwaita`, `roboto`, `ubuntu`; `googlesans` stays stock to match Google's web font), `realize()` runs `builders/darken.py` (`FT_Outline_EmboldenXY` with `DARKEN_X_EM = 0.0121 * darkening`, `DARKEN_Y_EM = 0.0121 * 1.25 * darkening`) into `~/.cache/fontlab/builds/<family>-<key>/`.
3. `fonts.install()` hard-links files into a staging directory, replaces `~/.local/share/fonts/fontlab/<family>` atomically, and calls `newer_than()` to push mtime past the current whole second so `fc-cache` does not skip back-to-back applies.

## Chromium text shim (`chromium/`)

Chromium only reads `--text-contrast` and `--text-gamma` from command-line flags and drops them when spawning renderer processes.

Three entry points load `fontlab-text-shim.so` and set `FONTCONFIG_FILE`:

1. `/usr/local/bin/<browser>` wrappers (`wrapper.sh` -> `chromium-env.sh`) for terminal launches and callers resolving through `PATH`.
2. `fontlab-launch` prepended to Chromium/Electron `.desktop` entries in `~/.local/share/applications/` (`apps.py`). Apps already covered by a `/usr/local/bin` wrapper are skipped so helpers like `omarchy-launch-browser` still see the browser command first.
3. Optional `session_shim=on` (`LD_PRELOAD` in `~/.config/uwsm/env` and `systemd --user`) for apps launched from window-manager keybinds or as AppImages.

Inside `chromium/text-shim.c`:

- `shim_init()` runs as a constructor, resolves libc symbols eagerly, checks whether `/proc/self/exe`'s directory has `icudtl.dat` plus `resources.pak` or `v8_context_snapshot.bin`, reads `FONTLAB_TEXT_CONF` (or `~/.config/fontlab/chromium-text.conf`), sets `FONTCONFIG_FILE` if unset and `~/.config/fontlab/chromium-fonts.conf` exists, and strips `fontlab-text-shim.so` from `LD_PRELOAD`. With `LCD_FILTER=box` in the conf (`chromium_lcd_filter=box` plus `antialias` `rgb`/`bgr`) it keeps itself in `LD_PRELOAD` and instead runs `patch_lcd_filter()`.
- `patch_lcd_filter()`: walks `dl_iterate_phdr()` over the main executable and any `libcef.so*` / `libelectron*`, scans their read-only (`PF_R`) `PT_LOAD` segments for Skia's stock `pack4xHToMask` table (`uint32[36]`), and on exactly one hit `mprotect`s the page RW, writes the 1-pixel box table, and sets it back to read-only. Each exec'd Chromium process (browser, zygote, GPU, utility) patches its own copy-on-write page; renderers fork from the zygote and inherit it. The zygote is the one that matters for web pages: patching only the zygote gives the full result, patching only the browser, GPU or renderer exec path does not. Cost: about 12 ms per exec'd process with cold pages, PSS unchanged.
- Zygote path: hooks `sendmsg()`, detects `base::Pickle` `"renderer"` fork messages, and splices `--text-contrast=...` and `--text-gamma=...` into the serialized argv.
- No-zygote path: hooks `execve`, `execv`, `execvp`, `execvpe`, and `posix_spawn`, checks for `--type=renderer`, and appends the flags using a stack buffer (no heap allocation after `fork()`).

## Isolated preview (`fontlab/preview.py`)

`compare_setup(state)` writes a separate fontconfig tree, symlinked font directory, and `chromium-text.conf` under `~/.cache/fontlab/preview/compare/`. It hides `~/.local/share/fonts/fontlab` with `<rejectfont>` and launches `/usr/bin/chromium` directly so `/usr/local/bin/chromium` does not interfere. Headless benchmarks follow the same isolation pattern (see `.agents/skills/render-benchmark/SKILL.md`).
