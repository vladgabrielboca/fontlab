# Architecture

`fontlab` reads `~/.config/fontlab/state.toml` and updates every managed output from `fontlab/apply.py`. Running `apply()` twice with the same state makes no changes on the second pass.

## How `apply()` works

```text
~/.config/fontlab/state.toml
        │
        ▼
  state.load() ──▶ Context.detect().effective(state)   (defaults for unavailable choices and locked settings)
        │
        ├──▶ 1. fonts.install(state)          ──▶ ~/.local/share/fonts/fontlab/<family>/
        │                                         (builds weights and darkening, cached in ~/.cache/fontlab/builds/)
        ├──▶ 2. fontconfig.confs(state, sets) ──▶ ~/.config/fontconfig/conf.d/70-fontlab-render.conf
        │                                     ──▶ ~/.config/fontconfig/conf.d/71-fontlab-web.conf
        │       fc-cache (if fonts or conf changed; notices Omarchy shell restart if fonts changed)
        │
        ├──▶ 3. chromium.apply(state, shim)   ──▶ ~/.config/fontlab/chromium-text.conf
        │                                     ──▶ ~/.config/fontlab/chromium-fonts.conf
        │                                     ──▶ ~/.config/uwsm/env (+ systemd --user LD_PRELOAD)
        │       (without the shim: chromium.remove_all() undoes all of step 3)
        │
        ├──▶ 4. vencord.apply(state)          ──▶ ~/.config/{vesktop,Vencord,equibop}/settings/quickCss.css
        │
        ├──▶ 5. desktop.apply_gsettings()     ──▶ GNOME org.gnome.desktop.interface keys
        │
        └──▶ 6. desktop.apply_environment()   ──▶ /etc/environment (only with --system / ! and != "keep")
```

## Settings, availability and locks

- `settings.py` holds every setting (`Setting`: choices, default, `help`, `affects`, `needs`, `active_when`) and the `WEB_FONTS` table.
- `packages.py` says which setting each package feeds (`weight_key`, `darkens`). `availability.needs()` and `packages.unlocking()` derive setting needs from that, so there is no second list.
- `Context.effective(state)` swaps unavailable values for defaults (with a notice) and then locked ones (`active_when` not met, silently). `Context.locks(state)` gives the reason per setting for the TUI and CLI. `state.toml` keeps the user's value either way.

## Paths (`fontlab/paths.py`)

Every path `fontlab` reads or writes lives on `paths.P` (`Paths(home)`). Unit tests call `paths.configure(tmp_home)` to redirect all reads and writes into a temp directory.

| Category | Path | Notes |
|---|---|---|
| State | `~/.config/fontlab/state.toml` | Only source of truth. |
| Presets | `~/.config/fontlab/presets/<name>.toml` | Named snapshots (`fontlab preset save/load`). |
| Font sources | `~/.local/share/fontlab/sources/<pkg>/` | Unmodified packages and `manifest.json`; files `0o444` (hard-linked on install). |
| Installed fonts | `~/.local/share/fonts/fontlab/<pkg>/` | Active family folders with `.fontlab-key` marker; swapped atomically via `replace_dir()`. |
| Fontconfig | `~/.config/fontconfig/conf.d/70-fontlab-render.conf` | AA, hinting, mono hinting, LCD filter, `small_bold`, Google Sans aliases, icon-font darkening exclusions, `<rejectfont>` globs. |
| Fontconfig | `~/.config/fontconfig/conf.d/71-fontlab-web.conf` | `sans-serif`/`system-ui`/Arial aliases (`inter`; absent for `system`). |
| Chromium | `~/.config/fontlab/chromium-text.conf` | `CONTRAST=..`, `GAMMA=..` and `LCD_FILTER=box`; removed when contrast and gamma match Chromium's Linux defaults (`0.2` / `1.2`) and the filter is stock. |
| Chromium | `~/.config/fontlab/chromium-fonts.conf` | Private `FONTCONFIG_FILE` for Chromium apps when `web_fonts != "system"` or `chromium_hinting` differs from `hinting`/`mono_hinting`. Maps the GTK UI font to the chosen web font so CSS `system-ui` follows `web_fonts`, and adds the Windows font dir plus `data/web-windows.conf` when `web_fonts=windows`. |
| Runtime | `~/.local/share/fontlab/runtime/fontlab-text-shim.so` | Built and installed by `install.sh` (replaced by rename: every process in the session maps it). |
| Session env | `~/.config/uwsm/env` | Single marked block adding the shim to `LD_PRELOAD` whenever it is installed, also synced to `systemctl --user`. |
| Cache | `~/.cache/fontlab/builds/` | Cached weight and darkening builds (pruned to `KEEP_BUILDS = 32` most recent). |
| Cache | `~/.cache/fontlab/preview/` | Profiles and isolated comparison configs for `fontlab preview`. |
| System (sudo) | `/etc/environment` | Only `FREETYPE_PROPERTIES` and `QT_NO_SYNTHESIZED_BOLD` lines touched. |

## Font packages and builders

1. `packages.py` downloads or imports stock files into a staging directory, writes `manifest.json`, sets files `0o444`, and swaps the directory into `~/.local/share/fontlab/sources/<id>/`. Nothing is built at install.
   - `<id>/400/` holds the stock static family (omitted for `jbm`, where the system font serves as the 400 base).
   - `<id>/variable/` holds the variable fonts heavier weights are made from (`Package.VARIABLE`). Installs from before 2026-11-28 have per-weight folders instead and no `variable/`; they still work at 400, and `has_weights()` makes the weight settings, `fontlab fonts`, `doctor` and the TUI ask for `fontlab fonts install <id>` once. `Manifest.from_json()` ignores their old keys.
   - `Package.weight_faces()` names the faces that change with the weight: `WeightFace(base, variable, method, axes)`. Inter: `Inter-Regular`/`Inter-Italic`, method `instance`, `opsz=14`. JetBrains Mono: the installed `JetBrainsMonoNerdFont-Regular`/`-Italic` (or plain JetBrains Mono), method `graft`, found when settings are applied, so its `replaces()` is live too.
2. `fonts.py` plans a `FontSet` per package in `fonts.families()` (packages with `installs=True`): the stock `sources` minus the rebuilt bases, the `faces` at the chosen weight, and the darkening (`inter` only; `googlesans` stays stock to match Google's web font). The cache key hashes `BUILDER_VERSION`, the package id, weight, darkening and every input file's fingerprint (inode, size, mtime), so a reinstall or a system update of the JetBrains Mono file makes the next apply build again. `realize()` sends every family that is not cached to one `builders/run.py build` call (JSON jobs on stdin, run in a `ProcessPoolExecutor`) through `toolchain.py`, which finds a Python with `fontTools` (system, `uv`, or a venv at `~/.local/share/fontlab/venv`). Results go to `~/.cache/fontlab/builds/<family>-<key>/` (pruned to `KEEP_BUILDS = 32`). Files that need no build are hard-linked from the sources. A weight change takes about 2.5 s, darkening included.
   - `instance`: `weights.instance()` at `wght` plus the fixed axes, then `_take_identity()` copies the stock face's `name`, `usWeightClass`, `fsSelection`, `achVendID` and `macStyle` and drops `STAT`/`avar`, so apps treat it as weight `400`. A hinted variable font without `cvar` only has bytecode for its default master, so other instances lose it.
   - `graft`: the installed file stays the base (Nerd Font icons and patcher tables kept), glyphs the variable font also has get its outlines, and bytecode is stripped.
   - Darkening: `builders/darken.py` (`FT_Outline_EmboldenXY` with `DARKEN_X_EM = 0.0121 * darkening`, `DARKEN_Y_EM = 0.0121 * 1.25 * darkening`), applied after the weight. Darkened fonts lose their TT bytecode and get `gasp` = smooth without grid fitting (`builders/hinting.py`), since the old instructions can snap the wider stems back at `hinting=full`.
   - Bump `fonts.BUILDER_VERSION` whenever anything in `builders/` changes its output.
3. `fonts.install()` hard-links files into a staging directory, replaces `~/.local/share/fonts/fontlab/<family>` atomically, and calls `newer_than()` to push mtime past the current whole second so `fc-cache` does not skip back-to-back applies.

## Chromium text shim (`chromium/`)

Chromium only reads `--text-contrast` and `--text-gamma` from command-line flags and drops them when spawning renderer processes.

One route loads `fontlab-text-shim.so`: `LD_PRELOAD` for the whole login, from a marked block in `~/.config/uwsm/env` plus `systemctl --user set-environment` (`chromium.apply_session_env()`), written whenever the shim is installed. Every process maps it, and all but Chromium's leave it after one `readlink` and `access()`. A new install or removal needs a new login. Until 2026-11-28 there were also `/usr/local/bin` wrappers and rewritten `.desktop` entries; `legacy.cleanup()` (on apply) and `install.sh` remove what they left.

Inside `chromium/text-shim.c`:

- `shim_init()` runs as a constructor, resolves libc symbols eagerly, checks whether `/proc/self/exe`'s directory has `icudtl.dat` plus `resources.pak` or `v8_context_snapshot.bin`, reads `FONTLAB_TEXT_CONF` (or `~/.config/fontlab/chromium-text.conf`), sets `FONTCONFIG_FILE` if unset and `~/.config/fontlab/chromium-fonts.conf` exists (remembering it in `fc_env`), and strips `fontlab-text-shim.so` from `LD_PRELOAD`. With `LCD_FILTER=box` in the conf (`chromium_lcd_filter=box` plus `antialias` `rgb`/`bgr`) it keeps itself in `LD_PRELOAD` and instead runs `patch_lcd_filter()`.
- `patch_lcd_filter()`: walks `dl_iterate_phdr()` over the main executable and any `libcef.so*` / `libelectron*`, scans their read-only (`PF_R`) `PT_LOAD` segments for Skia's stock `pack4xHToMask` table (`uint32[36]`), and on exactly one hit `mprotect`s the page RW, writes the 1-pixel box table, and sets it back to read-only. Each exec'd Chromium process (browser, zygote, GPU, utility) patches its own copy-on-write page; renderers fork from the zygote and inherit it. The zygote is the one that matters for web pages: patching only the zygote gives the full result, patching only the browser, GPU or renderer exec path does not. Cost: about 12 ms per exec'd process with cold pages, PSS unchanged.
- Browser process: hooks `__libc_start_main()` and hands `main()` an argv with `--text-contrast`/`--text-gamma` added (before any `--`), for the browser UI. Only for `BROWSER_EXES` (`chrome`, `chromium`, `brave`, `vivaldi-bin`, `msedge`) and only without `--type=`: Electron and CEF apps draw everything in renderers, and some treat unknown arguments as files to open. `/proc/<pid>/cmdline` still shows the original argv; `chrome://version` shows the one Chromium parsed.
- Zygote path: hooks `sendmsg()`, detects `base::Pickle` `"renderer"` fork messages, and splices `--text-contrast=...` and `--text-gamma=...` into the serialized argv.
- No-zygote path: hooks `execve`, `execv`, `execvp`, `execvpe`, `posix_spawn` and `posix_spawnp`, checks for `--type=renderer`, and appends the flags using a stack buffer (no heap allocation after `fork()`).
- `child_env()`: the same hooks drop the shim's own `FONTCONFIG_FILE=` entry from every child's environment (stack copy, up to `MAX_ENV` entries). Renderers get fonts from the browser process over IPC and do not need it, and anything else the app starts (an editor's terminal, `xdg-open`) keeps the desktop fontconfig. A `FONTCONFIG_FILE` the user set is passed on unchanged. With `LCD_FILTER=box`, Chromium children load the shim again and set it for themselves. `system()` and `popen()` spawn inside glibc and are not covered.

## Isolated preview (`fontlab/preview.py`)

`compare_setup(state)` writes a separate fontconfig tree, symlinked font directory, and `chromium-text.conf` under `~/.cache/fontlab/preview/compare/`. It hides `~/.local/share/fonts/fontlab` with `<rejectfont>` and launches the browser (`chromium.browser()`: the first of `chromium.BROWSERS`, `/usr/bin` first) with `LD_PRELOAD` removed, or pointed at the shim with `FONTLAB_TEXT_CONF` set to the preset's text conf. The live window preloads the shim explicitly, so it also works in a login that started before the shim was installed. Headless benchmarks follow the same isolation pattern (see `.agents/skills/render-benchmark/SKILL.md`).
