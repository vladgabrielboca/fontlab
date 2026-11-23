# fontlab

Font rendering settings for Linux in one place: antialiasing, hinting, stem darkening,
font weights, which font web pages get, and Chromium's text contrast and gamma.
Change a value and it applies right away, with an optional Chromium preview window
that restarts on every change.

```
  █▀▀ █▀█ █▄ █ ▀█▀ █   ▄▀█ █▄▄
  █▀  █▄█ █ ▀█  █  █▄▄ █▀█ █▄█   font rendering, one place

  RENDERING
  ▸ Antialiasing                grayscale ›
    Hinting                   ‹ slight ›
  ...
  INSTALL FONTS
    Inter                     ✓ installed  4.1
    SF Pro (Apple)              not installed, enter installs
```

Built and tested on Omarchy (Arch, Hyprland). It only needs fontconfig and Python, so
any distro and desktop should work. GNOME's gsettings are updated when the schema exists.

## Install

```
git clone https://github.com/<you>/fontlab ~/.local/share/fontlab-src
cd ~/.local/share/fontlab-src
./install.sh
fontlab
```

You need Python 3.11+ and fontconfig. Optional extras:

- A C compiler (`gcc`) builds the small library that passes contrast and gamma to Chromium. Without it those two settings are greyed out.
- `uv` or a system `python-fonttools` builds the font weights. Without either, fontlab makes a private venv the first time it needs one.
- `7z` (p7zip or 7zip) downloads SF Pro straight from Apple. Without it you can still import SF fonts from a folder.

`install.sh` asks for sudo once, to put launch wrappers for the Chromium-family apps it
finds (chromium, brave, chrome, vivaldi, edge, spotify, discord) in `/usr/local/bin`.
Run `./install.sh --no-wrappers` to skip that. Run it again after a `git pull`.

## Use

```
fontlab                          interactive screen
fontlab status                   every setting, and which differ from the default
fontlab list                     every setting's choices
fontlab set gamma=1.4 darkening=0.5
fontlab fonts                    font packages and whether they are installed
fontlab fonts install inter
fontlab fonts install sf --accept-license
fontlab fonts install windows --from /run/media/me/Windows/Windows/Fonts --accept-license
fontlab fonts remove sf
fontlab preset save NAME | load NAME | list | delete NAME
fontlab apply [--system]         make the system match the saved state
fontlab preview                  open the preview window once
fontlab doctor                   check what is installed and working
```

Keys on the screen: up/down move, left/right change a value, Enter opens the list of
choices or installs a font, `r` resets to the default, `x` removes a font, `p` toggles
the preview window, `s` saves a preset, `o` opens one, `!` writes `/etc/environment`
with sudo, `q` quits.

Most apps read font settings only at launch, so restart them to see a change. Terminal
fonts need a new terminal window. The FreeType setting needs a new login.

## Settings

| key | what it changes |
|---|---|
| antialias | grayscale, or subpixel rgb/bgr |
| hinting, mono_hinting | none/slight/medium/full, for proportional and monospace text |
| lcdfilter | FreeType's subpixel filter (Chromium ignores it) |
| darkening | macOS-style stem darkening baked into Inter and Adwaita Sans, 0 to 1 |
| ui_weight | Inter and Adwaita Sans Regular/Italic weight, 400 to 500 |
| mono_weight | JetBrains Mono Regular/Italic weight |
| sf_weight | SF Pro Text Regular/Italic weight |
| web_fonts | what `sans-serif`, `system-ui`, Arial, Helvetica and friends become: default, inter, sf, or windows (Chromium only) |
| contrast, gamma | Skia's text contrast and gamma in Chromium apps |
| freetype_darkening | FREETYPE_PROPERTIES in `/etc/environment`. `keep` (the default) never touches the file |

A setting that needs a font you don't have is greyed out and says which one.

## Fonts

fontlab never ships font files. It builds or imports them on your machine into
`~/.local/share/fontlab/sources`.

| package | where it comes from |
|---|---|
| inter | Inter 4.1 release from github.com/rsms/inter (checksum verified), heavier weights built from the variable font |
| adwaita | your installed Adwaita Sans, rebuilt as static files with heavier weights |
| jbm | JetBrains Mono 2.304 outlines at each weight, put on your installed JetBrains Mono or its Nerd Font so the icons stay |
| sf | SF Pro, SF Mono and New York, downloaded from Apple or imported from a folder. Apple's license allows use only on Apple platforms, so you have to accept that yourself |
| windows | Windows 11 fonts copied from a Windows install's Fonts folder (fontlab looks in `/run/media`, `/media` and `/mnt`). Used only by Chromium apps. You need a Windows license |

Installs are atomic: a failed or cancelled install leaves the old package as it was.

## How it works

Everything comes from one file, `~/.config/fontlab/state.toml`. Each apply rebuilds the
outputs from it and only writes files whose content changed:

- `~/.local/share/fonts/fontlab/` holds the chosen weight of each family, plus darkened copies (cached in `~/.cache/fontlab`). The system copies of those families are hidden with fontconfig `rejectfont`, so nothing in `/usr/share` is modified.
- `~/.config/fontconfig/conf.d/70-fontlab-render.conf` and `71-fontlab-web.conf` hold the rendering and font-substitution rules. If your distro forces `sans-serif` to a font (Omarchy uses Liberation Sans), fontlab detects that and overrides it.
- The `/usr/local/bin` wrappers start the real browser with `--text-contrast` and `--text-gamma` and preload a small library that adds the same flags to the renderer processes, because Chromium's zygote drops them otherwise. With `web_fonts=windows` they also point Chromium at a private fontconfig file that adds the Windows fonts.
- gsettings `font-antialiasing`, `font-rgba-order` and `font-hinting`, when the GNOME schema exists.

## Uninstall

```
./uninstall.sh            remove outputs and wrappers, keep fonts and presets
./uninstall.sh --purge    also delete font packages, presets, state and cache
```

`/etc/environment` is left as it is.

## Tests

```
python3 -m unittest discover tests
```

## Credits

The darkening code is a Python port of FreeType's `FT_Outline_EmboldenXY`, with the
macOS strength measured by the Pathfinder project. Inter is by Rasmus Andersson,
JetBrains Mono by JetBrains, both under the SIL Open Font License.
