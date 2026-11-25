# fontlab

`fontlab` is a Linux font-rendering configuration tool (TUI + CLI) originally built on Omarchy (Arch Linux + Hyprland). From a single source of truth (`~/.config/fontlab/state.toml`), it manages fontconfig rules, locally built weighted/darkened static fonts, GNOME `gsettings`, Vencord/Vesktop CSS, `/etc/environment` (`FREETYPE_PROPERTIES`, `QT_NO_SYNTHESIZED_BOLD`), and an `LD_PRELOAD` C shim (`chromium/text-shim.c`) that injects Skia `--text-contrast` / `--text-gamma` and private `FONTCONFIG_FILE` into Chromium and Electron apps.

## Start Here

Read only what your task needs:

- **[docs/README.md](docs/README.md)** — Full documentation index.
- **[docs/internals/architecture.md](docs/internals/architecture.md)** — Module map, `apply()` pipeline, file ownership (`paths.py`), Chromium shim & launcher flow, and font package lifecycle.
- **[docs/internals/rendering-pipeline.md](docs/internals/rendering-pipeline.md)** — Upstream Linux/Chromium/Fontations/Skia/FreeType mechanics (`SkMaskGamma`, `SkTypeface_Fontations`, `FREETYPE_PROPERTIES`, hinting modes). **Read before proposing rendering tweaks or new knobs.**
- **[docs/research/experiments.md](docs/research/experiments.md)** — Record of everything already tested (headless Chromium Fontations + Firefox FreeType pixel benchmarks, dead ends, verified presets, Google Sans findings). **Check this before running new rendering experiments so we never re-test settled ground.**

## Repo Skills

Reusable task playbooks live in `.agents/skills/` (also linked at `.claude/skills/`):

- **`.agents/skills/render-benchmark/SKILL.md`** — How to run isolated headless Chromium (Fontations) & Firefox (FreeType) pixel-level rendering benchmarks without touching `~/.config/fontlab/state.toml`, measure physical linear-light parity & white-bloom, and record results in `docs/research/experiments.md`.
- **`.agents/skills/add-font-package/SKILL.md`** — Checklist for adding or modifying a font package, builder, or setting across `packages.py`, `builders/`, `fonts.py`, `fontconfig.py`, `chromium.py`, `availability.py`, `settings.py`, and tests.

## Repo Layout

```text
bin/fontlab                  Entrypoint script (linked to ~/.local/bin/fontlab by install.sh)
install.sh / uninstall.sh    Builds C shim, installs runtime & /usr/local/bin wrappers
fontlab/
  settings.py                Fixed-choice setting registry (SETTINGS, BY_KEY, DEFAULTS)
  state.py                   state.toml and presets/<name>.toml read/write/normalize/validate
  paths.py                   Single source of truth for every input/output/cache path
  availability.py            Context.detect(): gates settings/choices on installed packages & shim
  packages.py                Download/import/build manifests (inter, adwaita, jbm, googlesans, roboto, sf, windows)
  fonts.py                   Plans, caches darkened builds, and atomically installs into ~/.local/share/fonts/fontlab
  fontconfig.py              Generates 70-fontlab-render.conf and 71-fontlab-web.conf
  chromium.py                Generates chromium-text.conf, chromium-fonts.conf, uwsm/systemd session_shim
  apps.py                    Detects Chromium/Electron desktop entries and wraps Exec with fontlab-launch
  desktop.py                 gsettings + sudo /etc/environment + Omarchy shell restart notice
  vencord.py                 Marked QuickCSS block for Vesktop/Vencord/Equibop
  apply.py                   Idempotent apply() and uninstall() orchestrator
  preview.py                 Live preview and isolated compare_setup() Chromium window
  cli.py / tui.py            CLI subcommands and curses TUI
  builders/                  Runs in isolated Python with fontTools — NEVER imports fontlab
    run.py                   Subprocess dispatcher (darken + weight instancers)
    weights.py               Variable-to-static weight instancers (fontTools)
    darken.py                Python port of FreeType FT_Outline_EmboldenXY
chromium/
  text-shim.c                LD_PRELOAD shim (sendmsg zygote pickle + exec*/posix_spawn no-zygote)
  chromium-env.sh            POSIX sh snippet setting FONTLAB_ARGS, LD_PRELOAD, FONTCONFIG_FILE
  wrapper.sh / fontlab-launch / Makefile
tests/test_fontlab.py        Unit tests (stdlib unittest, isolated fake HOME via paths.configure)
```

## Essential Commands

```bash
# Run the full test suite (fast, zero external deps, uses fake HOME)
python3 -m unittest discover -s tests -v

# Rebuild the C shim only (no sudo)
make -C chromium

# Full local install / update (rebuilds shim, updates ~/.local/share/fontlab/runtime & /usr/local/bin wrappers)
./install.sh

# Inspect live system state without changing anything
fontlab status
fontlab fonts
fontlab apps
fontlab doctor
```

## Non-Negotiable Rules & Invariants

1. **Never mutate the user's live config during research or tests.**
   - Unit tests MUST call `paths.configure(tmp_home)`.
   - Rendering benchmarks MUST use isolated temp dirs (`FONTCONFIG_FILE`, `FONTLAB_TEXT_CONF`, `/usr/bin/chromium` bypassing `/usr/local/bin/chromium`)—never overwrite `~/.config/fontlab/state.toml` or thrash `~/.cache/fontlab/builds` (`KEEP_BUILDS = 16`).
2. **`state.toml` is the only source of truth; `apply()` must stay idempotent.**
   - Every writer uses `write_if_changed()` or atomic `replace_dir()`. Running `fontlab apply` twice must report `"already applied"` on the second run.
   - At Chromium's own defaults (`contrast=0.2`, `gamma=1.2`, `web_fonts=system`), `fontlab` must add no launcher wrapping or text conf (`ChromiumDefaultsTest`).
3. **Never touch `/usr/share`.**
   - System fonts replaced by `fontlab` are hidden via `<rejectfont><glob>` in `70-fontlab-render.conf`.
   - The only root-owned files `fontlab` ever touches are `/usr/local/bin/<browser>` wrappers (`install.sh`) and the `FREETYPE_PROPERTIES` / `QT_NO_SYNTHESIZED_BOLD` lines in `/etc/environment` (only on explicit `--system` / `!` with sudo, never when set to `"keep"`).
4. **`fontlab/builders/` has zero dependency on `fontlab`.**
   - `toolchain.py` invokes `builders/run.py` under whichever Python has `fontTools` (system, `uv`, or `~/.local/share/fontlab/venv`). Never import `fontlab.*` inside `builders/`.
5. **Respect fontconfig & C shim subtleties.**
   - **fc-cache 1-second mtime granularity**: When replacing font directories, preserve `fonts.newer_than()` so two applies in the same second aren't ignored by `fc-cache`.
   - **Strong fontconfig aliases**: Chromium ignores weak family matches—all family rewrites in `fontconfig.py` and `chromium.py` use `mode="prepend" binding="strong"`.
   - **Async-signal safety in `chromium/text-shim.c`**: All `dlsym()` lookups and `fopen()` config reads happen eagerly in `__attribute__((constructor)) shim_init()`, NEVER between `fork()` and `exec*()`. Non-Chromium processes must exit `shim_init()` immediately after checking for `icudtl.dat` + (`resources.pak` or `v8_context_snapshot.bin`), and Chromium strips `fontlab-text-shim.so` from `LD_PRELOAD` so child terminals/processes don't inherit it.
   - **Read-only source files**: `packages.py` marks files in `~/.local/share/fontlab/sources/` `0o444` because `fonts.py` hard-links them into `~/.local/share/fonts/fontlab/`.
6. **Zero third-party Python dependencies for the core package.**
   - Core `fontlab` runs on Python 3.11+ stdlib only (`tomllib`, `curses`, `xml.etree`, etc.). `fontTools` is only used inside `builders/`.
7. **Always run `python3 -m unittest discover -s tests -v` after code changes** (and `make -C chromium` if touching `chromium/text-shim.c`).
8. **Record new rendering findings.**
   - Whenever you benchmark a font, hinting mode, gamma/contrast value, or rendering hypothesis, append the verified outcome (including failed/disqualified ideas) to [docs/research/experiments.md](docs/research/experiments.md).
