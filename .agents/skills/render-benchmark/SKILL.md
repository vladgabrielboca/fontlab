---
name: render-benchmark
description: Run isolated, pixel-level font rendering benchmarks in headless Chromium (Fontations) and headless Firefox (FreeType) without modifying the user's live fontlab config. Use when comparing fontlab settings, verifying a font package or builder change, testing gamma/contrast/hinting/darkening trade-offs, or comparing Fontations against FreeType.
---

# Isolated Rendering Benchmark

Use this procedure whenever you compare visual or pixel-level rendering changes in `fontlab`.

## Before you start

1. Check `docs/research/experiments.md`. Do not re-run configs already listed under "Ruled out" unless a code change alters them.
2. Check `docs/internals/rendering-pipeline.md` so the test matrix matches how Skia/Fontations and FreeType actually behave.
3. Keep `~/.config/fontlab/state.toml` and `~/.cache/fontlab/builds/` untouched. Build darkened test fonts in a temp directory (for example `/tmp/fontlab-bench/` or the conversation scratch dir) and delete temporary browser profiles after each capture.

## Isolation rules

### Headless Chromium (Fontations)

- Remove `LD_PRELOAD` from the browser's environment (`env -u LD_PRELOAD ...`). The login session preloads fontlab's shim into every process, and with it the browser reads the user's live `chromium-text.conf` and `chromium-fonts.conf`. Get the browser with `python3 -c 'from fontlab import chromium; print(chromium.browser())'` from the repo root (on this machine `/usr/bin/brave-origin`; `/usr/bin/chromium` is not installed).
- Set `TMPDIR=/tmp` and `XDG_RUNTIME_DIR=/tmp`. Longer temp paths crash Chromium with `FATAL: process_singleton_posix.cc: Socket path too long`.
- Mirror `fontlab.preview.compare_setup()` in your temp dir:
  - Build or symlink only the font files needed for the test into `<tmp>/fonts/<family>/`.
  - Write `<tmp>/render.conf`, `<tmp>/web.conf`, and `<tmp>/fonts.conf` via `chromium.private_fonts_conf(..., extra_dirs=(font_dir,), hidden_dirs=(paths.P.installed_fonts,))`.
  - Run `fc-cache <font_dir>` with `FONTCONFIG_FILE=<tmp>/fonts.conf`.
  - Pop `LD_PRELOAD` and `FONTLAB_TEXT_CONF` from `env`. When testing non-default `contrast`/`gamma`, write `<tmp>/chromium-text.conf`, and set `FONTLAB_TEXT_CONF` and `LD_PRELOAD=~/.local/share/fontlab/runtime/fontlab-text-shim.so`. The shim adds `--text-contrast`/`--text-gamma` itself.
- Pass `--headless=new --no-first-run --no-default-browser-check --hide-scrollbars --force-device-scale-factor=1 --window-size=640,460 --user-data-dir=<tmp>/profile --screenshot=<out.png> file://<html_path>`.
- Run a quick 3-config probe first (baseline, high gamma, heavier weight) to confirm the knobs actually change pixels before launching a large sweep.

### Headless Firefox (FreeType reference)

- Run `/usr/bin/firefox --headless --no-remote --profile <tmp>/profile --window-size=640,460 --screenshot=<out.png> file://<html_path>`.
- Write `user_pref("layout.css.devPixelsPerPx", "1.0");` to `<tmp>/profile/user.js`.
- Set `MOZ_DISABLE_CONTENT_SANDBOX=1` so the isolated `FONTCONFIG_FILE` and `FREETYPE_PROPERTIES` reach content processes, and unset `LD_PRELOAD` and `FONTLAB_TEXT_CONF`.
- Use `fontlab.desktop.FREETYPE` strings (`"all"`, `"strong"`, or `"truetype:interpreter-version=35"`) for `FREETYPE_PROPERTIES`.

## Test page

Test across multiple backgrounds and sizes:

- 5 surfaces:
  1. `#ffffff` on `#000000` (pure black, worst halation)
  2. `#ffffff` on `#121723` (dark navy chat/UI bubble)
  3. `#e6e6e6` on `#24272e` (soft dark UI)
  4. `#ffffff` on `#49659e` (colored button/bubble, which exposes Skia's `dst = 1 - src` assumption)
  5. `#1a1a1a` on `#ffffff` (light mode)
- Sizes: `12px`, `13px`, `14px`, `15px`, `16px`.
- Glyph checks: straight stems (`HIIIllnnmm`), diagonals (`wwvvkkxxzz`, Waxweiler's gamma test), tight counters (`e a s g o c 8 6`), and body prose.

## Pixel metrics (`uv run --with pillow --with numpy --with fonttools`)

1. **Physical linear-light ink weight**: `sRGB -> linear` luminance per surface, normalized to stock `w400 d0.00 slight c0.2 g1.2 = 1.00x`. Plain sRGB luminance hides how much high gamma brightens dark-mode edges on a gamma-2.2 display.
2. **White-stem doubling / bloom (`dblW`)**: fraction of active pixels on `#000`/`#121723` where two adjacent horizontal pixels both have sRGB alpha `>= 0.72`. Catches glowing, doubled white stems at high gamma.
3. **3-pixel stem bleed (`bld3`)**: fraction of vertical runs (width `1..4px` at alpha `>= 0.10`) spanning `>= 3` pixels. Catches `ui_weight > 400` stem blur under `slight` hinting.
4. **Edge steepness (`vSteep`, `hSteep`)**: $\sum |\nabla \alpha|^2 / \sum |\nabla \alpha|$ along X and Y.
5. **Tracking shift (`dw`)**: max line-width delta vs. stock across `12–16px` (catches `hinting=full` integer-advance jumps).
6. **Chroma fringing (`chroma`)**: mean max-channel deviation from the expected `(fg - bg)` gray ramp (catches RGB subpixel fringes).

## Visual check

Metrics alone miss artifacts like blotchy vertices and size jumps. Generate and inspect both:

- A 1x native strip across `12–16px` on every surface.
- A 3x or 4x nearest-neighbor crop of stems (`HIIIllnnmm`) and diagonals (`wwvvkkxxzz`) to catch corner blotches and color fringes.

## Wrap-up

1. Check `git status` and confirm `~/.config/fontlab/state.toml` was not modified.
2. Append verified results (and any new dead ends) to `docs/research/experiments.md`.
