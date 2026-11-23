# fontlab

Font rendering settings for this desktop (Omarchy, Hyprland, Chromium) in one place.
Run `fontlab` for an interactive screen, or `fontlab set key=value` from scripts.

It replaces the old separate commands (`mac-darken`, `inter-weight`, `jbm-weight`,
`sf-weight`, `sf-trial`, `chromium-text`, `chromium-ms-fonts`). Those each edited the
same font files and configs, so the last one run won. fontlab keeps one state file and
rebuilds every output from it.

## Use

```
fontlab                          interactive screen
fontlab status                   every setting, and which differ from the default
fontlab list                     every setting's choices
fontlab set gamma=1.4 darkening=0.5
fontlab preset save NAME | load NAME | list | delete NAME
fontlab apply [--system]         make the system match state.toml (--system: sudo for /etc/environment)
fontlab preview                  open the preview window once
fontlab clean-cache              delete cached darkened fonts
```

Keys on the screen: up/down move, left/right change, Enter opens a list of choices,
`r` resets to the default, `p` toggles the preview window, `s` saves a preset,
`o` opens a preset, `!` writes `/etc/environment` with sudo, `q` quits.

The preview window is Chromium with its own profile and a test page (text on black,
dark grey, white and light grey). It restarts after every change, because Chromium
reads these settings only at launch. Other apps need a restart too; terminal fonts
need a new terminal window. The FreeType setting needs a new login.

## Settings

| key | what it changes | where |
|---|---|---|
| antialias | grayscale or subpixel rgb/bgr | fontconfig, gsettings |
| hinting, mono_hinting | none/slight/medium/full, proportional and monospace | fontconfig, gsettings |
| lcdfilter | FreeType subpixel filter (Chromium ignores it) | fontconfig |
| darkening | macOS-style stem darkening baked into Inter and Adwaita Sans, 0 to 1 | font files |
| ui_weight | Inter and Adwaita Sans Regular/Italic weight | font files |
| mono_weight | JetBrains Mono Regular/Italic weight | font files |
| sf_weight | SF Pro Text Regular/Italic weight | font files |
| web_fonts | inter, sf, or windows (Chromium only, others keep Inter) | fontconfig |
| contrast, gamma | Skia text contrast and gamma | Chromium shim + flags |
| freetype_darkening | FREETYPE_PROPERTIES: off, cff, all | /etc/environment |

## Layout

```
fontlab/settings.py     the settings: key, choices, default, help
fontlab/state.py        state.toml and presets
fontlab/apply.py        runs every step below; each writes only when its output changes
fontlab/fonts.py        pick source files per weight, darken (cached), install per family
fontlab/fontbuild.py    the darkening itself; runs under `uv run --with fonttools`
fontlab/fontconfig.py   70-fontlab-render.conf and 71-fontlab-web.conf
fontlab/chromium.py     shim config, flags files, private fontconfig for Windows fonts
fontlab/desktop.py      gsettings and /etc/environment
fontlab/preview.py      the preview window
fontlab/tui.py          the interactive screen
fontlab/cli.py          the command line
chromium/               LD_PRELOAD shim source, chromium-env.sh, wrapper template
scripts/migrate_legacy.py   one-time move from the old commands
```

## Files

Inputs (read-only):
- `~/.local/share/fontlab/sources/<family>/400/`: the full stock family.
- `~/.local/share/fontlab/sources/<family>/<weight>/`: only the faces that change at that weight.
- `~/.local/share/ms-fonts/`: Windows 11 fonts, used only by Chromium.

State: `~/.config/fontlab/state.toml` and `~/.config/fontlab/presets/`.

Outputs (owned by fontlab, rewritten from state):
- `~/.local/share/fonts/fontlab/<family>/`: each family folder is replaced as a whole.
- `~/.config/fontconfig/conf.d/70-fontlab-render.conf` and `71-fontlab-web.conf`.
- `~/.config/fontlab/chromium-text.conf` (shim) and `chromium-fonts.conf` (windows only).
- gsettings `org.gnome.desktop.interface` font-antialiasing, font-rgba-order, font-hinting.

Shared files, where fontlab edits only its own lines:
- `~/.config/chromium-flags.conf` and `~/.config/brave-origin-flags.conf`: `--text-contrast`, `--text-gamma`.
- `/etc/environment`: `FREETYPE_PROPERTIES`.

Cache: `~/.cache/fontlab/builds` (the 16 most recent darkened builds), `~/.cache/fontlab/preview`.

## Install

```
python3 scripts/migrate_legacy.py --dry-run   # once, from the old commands
python3 scripts/migrate_legacy.py
./install.sh                                  # shim, ~/.local/bin/fontlab, wrappers (sudo)
fontlab apply
```

Tests: `python3 -m unittest discover -s tests -t .`

SF and Windows fonts are proprietary. They stay in `~/.local/share` and never go in this repo.
