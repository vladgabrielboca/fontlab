# fontlab

`fontlab` configures Linux font rendering from a single file (`~/.config/fontlab/state.toml`). It writes fontconfig rules, builds static weighted and darkened fonts, updates GNOME `gsettings` and Vencord/Vesktop QuickCSS, optionally edits `/etc/environment`, and injects Skia `--text-contrast`, `--text-gamma`, and a private `FONTCONFIG_FILE` into Chromium and Electron apps through `chromium/text-shim.c`.

## Docs

Read only what applies to your task:

- [docs/README.md](docs/README.md): documentation index.
- [docs/internals/architecture.md](docs/internals/architecture.md): module layout, `apply()` flow, managed paths (`paths.py`), font package builds, and the Chromium shim.
- [docs/internals/rendering-pipeline.md](docs/internals/rendering-pipeline.md): upstream Chromium, Fontations, Skia (`SkMaskGamma`, `SkTypeface_Fontations`), and FreeType behavior. Read this before proposing new settings or changing defaults.
- [docs/research/experiments.md](docs/research/experiments.md): pixel benchmarks already run in headless Chromium and Firefox, plus ruled-out ideas and Google Sans notes. Check this before running new benchmarks.

## Repo skills

Task skills live in `.agents/skills/` (also linked at `.claude/skills/`):

- `.agents/skills/render-benchmark/SKILL.md`: run isolated headless Chromium (Fontations) and Firefox (FreeType) pixel comparisons without touching live config, then log results in `docs/research/experiments.md`.
- `.agents/skills/add-font-package/SKILL.md`: checklist for adding or changing a font package or rendering setting across the codebase.

## Repo layout

```text
bin/fontlab                  Entrypoint script (linked to ~/.local/bin/fontlab by install.sh)
install.sh / uninstall.sh    Builds C shim, installs runtime and /usr/local/bin wrappers
fontlab/
  settings.py                Fixed-choice setting registry (SETTINGS, BY_KEY, DEFAULTS)
  state.py                   state.toml and presets/<name>.toml read/write/normalize/validate
  paths.py                   Every input, output, and cache path on paths.P
  availability.py            Context.detect(): gates settings/choices on installed packages and shim
  packages.py                Download/import/build manifests (inter, adwaita, jbm, googlesans, roboto, sf, windows)
  fonts.py                   Plans, caches darkened builds, and atomically installs into ~/.local/share/fonts/fontlab
  fontconfig.py              Generates 70-fontlab-render.conf and 71-fontlab-web.conf
  chromium.py                Generates chromium-text.conf, chromium-fonts.conf, uwsm/systemd session_shim
  apps.py                    Detects Chromium/Electron desktop entries and wraps Exec with fontlab-launch
  desktop.py                 gsettings, sudo /etc/environment, and Omarchy shell restart notice
  vencord.py                 Marked QuickCSS block for Vesktop/Vencord/Equibop
  apply.py                   Idempotent apply() and uninstall() orchestrator
  preview.py                 Live preview and isolated compare_setup() Chromium window
  cli.py / tui.py            CLI subcommands and curses TUI
  builders/                  Runs in isolated Python with fontTools (never imports fontlab)
    run.py                   Subprocess dispatcher (darken + weight instancers)
    weights.py               Variable-to-static weight instancers (fontTools)
    darken.py                Python port of FreeType FT_Outline_EmboldenXY
chromium/
  text-shim.c                LD_PRELOAD shim (sendmsg zygote pickle + exec*/posix_spawn no-zygote)
  chromium-env.sh            POSIX sh snippet setting FONTLAB_ARGS and LD_PRELOAD (the shim sets FONTCONFIG_FILE)
  wrapper.sh / fontlab-launch / Makefile
tests/test_fontlab.py        Unit tests (stdlib unittest, fake HOME via paths.configure)
```

## Commands

```bash
# Run the test suite (stdlib only, uses a fake HOME)
python3 -m unittest discover -s tests -v

# Rebuild the C shim without sudo
make -C chromium

# Full local install/update (rebuilds shim, updates ~/.local/share/fontlab/runtime and /usr/local/bin wrappers)
./install.sh

# Inspect live system state
fontlab status
fontlab fonts
fontlab apps
fontlab doctor
```

## Rules

1. **Leave the user's live config untouched during tests and research.**
   - Unit tests call `paths.configure(tmp_home)`.
   - Benchmarks run in temp directories with isolated `FONTCONFIG_FILE`, `FONTLAB_TEXT_CONF`, and `/usr/bin/chromium` (bypassing `/usr/local/bin/chromium`). Do not write to `~/.config/fontlab/state.toml` or fill `~/.cache/fontlab/builds` (`KEEP_BUILDS = 16`).

2. **Keep `state.toml` as the single source of truth and `apply()` idempotent.**
   - Writers use `write_if_changed()` or atomic `replace_dir()`. Running `fontlab apply` twice must report `"already applied"` on the second run.
   - At Chromium's Linux defaults (`contrast=0.2`, `gamma=1.2`, `web_fonts=system`), `fontlab` writes no text conf and wraps no desktop entries (`ChromiumDefaultsTest`).

3. **Never edit `/usr/share`.**
   - Replaced system fonts are hidden through `<rejectfont><glob>` in `70-fontlab-render.conf`.
   - The only root-owned files `fontlab` touches are `/usr/local/bin/<browser>` wrappers (`install.sh`) and the `FREETYPE_PROPERTIES` / `QT_NO_SYNTHESIZED_BOLD` lines in `/etc/environment` (only on explicit `--system` or `!` with sudo, never when set to `"keep"`).

4. **Keep `fontlab/builders/` independent of `fontlab`.**
   - `toolchain.py` invokes `builders/run.py` under whichever Python has `fontTools` (system, `uv`, or `~/.local/share/fontlab/venv`). Never import `fontlab.*` inside `builders/`.

5. **Preserve fontconfig and C shim details.**
   - `fc-cache` has 1-second mtime granularity, so directory swaps must keep `fonts.newer_than()` to avoid skipped cache updates on rapid applies.
   - Chromium ignores weak fontconfig aliases. Every family rewrite in `fontconfig.py` and `chromium.py` uses `mode="prepend" binding="strong"`.
   - `chromium/text-shim.c` must stay async-signal-safe between `fork()` and `exec*()`. `FONTCONFIG_FILE` is set by the shim inside the Chromium process only and dropped from children (`child_env()`); never export it from `chromium-env.sh` again, or every program an Electron app starts inherits Chromium's private fontconfig. Resolve `dlsym()` handles and read config files eagerly in `__attribute__((constructor)) shim_init()`. Non-Chromium processes exit `shim_init()` right after checking for `icudtl.dat` plus `resources.pak` or `v8_context_snapshot.bin`, and Chromium strips `fontlab-text-shim.so` from `LD_PRELOAD` so child processes do not inherit it, except with `LCD_FILTER=box`, where every Chromium process keeps it and patches Skia's LCD table in its constructor (never after `fork()`).
   - `packages.py` marks files in `~/.local/share/fontlab/sources/` as `0o444` because `fonts.py` hard-links them into `~/.local/share/fonts/fontlab/`.

6. **Keep core `fontlab` stdlib-only.**
   - Core code targets Python 3.11+ stdlib (`tomllib`, `curses`, `xml.etree`). `fontTools` is confined to `builders/`.

7. **Run checks after edits.**
   - Run `python3 -m unittest discover -s tests -v` after Python changes, and `make -C chromium` after touching `chromium/text-shim.c`.

8. **Log rendering experiments.**
   - When you benchmark a font or rendering setting, append the outcome (including ruled-out ideas) to [docs/research/experiments.md](docs/research/experiments.md).
