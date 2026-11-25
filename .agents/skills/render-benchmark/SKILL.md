---
name: render-benchmark
description: Run isolated, pixel-level font rendering benchmarks in headless Chromium (Fontations) and headless Firefox (FreeType) without modifying the user's live fontlab config. Use when comparing fontlab settings, verifying a font package or builder change, testing gamma/contrast/hinting/darkening trade-offs, or comparing Fontations against FreeType.
---

# Isolated Rendering Benchmark

Use this procedure whenever evaluating visual or pixel-level rendering changes in `fontlab`.

## Before You Start

1. **Check `docs/research/experiments.md` first** — do not re-run configs or hypotheses already settled in the "Ruled Out" table unless a code change invalidates them.
2. **Check `docs/internals/rendering-pipeline.md`** so your test matrix is grounded in real Skia/Fontations/FreeType behavior rather than arbitrary parameter sweeps.
3. **Never modify `~/.config/fontlab/state.toml` or `~/.cache/fontlab/builds/`** during benchmarks. Build darkened test fonts into a temporary scratch folder (e.g. `/tmp/fontlab-bench/` or the conversation scratch dir) and delete temporary Chromium/Firefox profiles after each capture.

## Isolation Rules (Critical Gotchas)

### Headless Chromium (Fontations)
- **Always invoke `/usr/bin/chromium`**, NOT `chromium` (which hits `/usr/local/bin/chromium` and injects the user's live `chromium-text.conf` and `chromium-fonts.conf`).
- **Set `TMPDIR=/tmp` and `XDG_RUNTIME_DIR=/tmp`**: long temp paths crash Chromium with `FATAL: process_singleton_posix.cc: Socket path too long`.
- **Mirror `fontlab.preview.compare_setup()`** in your own temp dir:
  - Build/symlink only the font files needed for the test into `<tmp>/fonts/<family>/`.
  - Write `<tmp>/render.conf`, `<tmp>/web.conf`, and `<tmp>/fonts.conf` via `chromium.private_fonts_conf(..., extra_dirs=(font_dir,), hidden_dirs=(paths.P.installed_fonts,))`.
  - Run `fc-cache <font_dir>` with `FONTCONFIG_FILE=<tmp>/fonts.conf`.
  - Pop `LD_PRELOAD` and `FONTLAB_TEXT_CONF` from `env`; when testing non-default `contrast`/`gamma`, write `<tmp>/chromium-text.conf`, set `FONTLAB_TEXT_CONF` and `LD_PRELOAD=~/.local/share/fontlab/runtime/fontlab-text-shim.so`, and pass `--text-contrast=<c> --text-gamma=<g>`.
- **Flags**: `--headless=new --no-first-run --no-default-browser-check --hide-scrollbars --force-device-scale-factor=1 --window-size=640,460 --user-data-dir=<tmp>/profile --screenshot=<out.png> file://<html_path>`.
- **Verify knobs took effect** on a quick 3-run probe (baseline vs high gamma vs heavier weight) before running a large sweep.

### Headless Firefox (FreeType Reference)
- Invoke `/usr/bin/firefox --headless --no-remote --profile <tmp>/profile --window-size=640,460 --screenshot=<out.png> file://<html_path>`.
- Write `user_pref("layout.css.devPixelsPerPx", "1.0");` to `<tmp>/profile/user.js`.
- Set `MOZ_DISABLE_CONTENT_SANDBOX=1` so the isolated `FONTCONFIG_FILE` and `FREETYPE_PROPERTIES` reach content processes, and unset `LD_PRELOAD` / `FONTLAB_TEXT_CONF`.
- Use `fontlab.desktop.FREETYPE` strings (`"all"`, `"strong"`, or `"truetype:interpreter-version=35"`) for `FREETYPE_PROPERTIES`.

## Test Page Requirements

Never test only one background or one font size. Include at least:
- **5 realistic surfaces**:
  1. `#ffffff` on `#000000` (pure black / max halation)
  2. `#ffffff` on `#121723` (dark navy chat/UI bubble)
  3. `#e6e6e6` on `#24272e` (standard soft dark UI)
  4. `#ffffff` on `#49659e` (colored button/bubble — exposes Skia's `dst = 1 - src` mismatch)
  5. `#1a1a1a` on `#ffffff` (standard light mode)
- **Sizes**: `12px`, `13px`, `14px`, `15px`, `16px`.
- **Glyph stress tests**: straight stems (`HIIIllnnmm`), diagonals (`wwvvkkxxzz` — Waxweiler's gamma test), tight counters (`e a s g o c 8 6`), and real prose.

## Pixel Metrics to Compute (via `uv run --with pillow --with numpy --with fonttools`)

1. **Physical linear-light ink weight** (`sRGB → linear` luminance per surface, normalized to stock `w400 d0.00 slight c0.2 g1.2 = 1.00×`) — never rely on sRGB luminance alone, because it hides how aggressively high gamma brightens dark-mode edges on a real gamma-2.2 display.
2. **White-stem doubling / bloom (`dblW`)**: fraction of active pixels on `#000`/`#121723` where two adjacent horizontal pixels both have sRGB alpha `≥ 0.72`. Catches the "too white / doubled" high-gamma artifact.
3. **3-pixel stem bleed (`bld3`)**: fraction of vertical runs (width `1..4px` at alpha `≥ 0.10`) spanning `≥ 3` pixels. Catches `ui_weight > 400` stem blur under `slight` hinting.
4. **Edge steepness (`vSteep`, `hSteep`)**: $\sum |\nabla \alpha|^2 / \sum |\nabla \alpha|$ along X and Y.
5. **Tracking / width shift (`dw`)**: max line-width delta vs. stock across `12–16px` (catches `hinting=full` integer-advance jumps).
6. **Chroma fringing (`chroma`)**: mean max-channel deviation from expected `(fg - bg)` gray ramp (catches RGB subpixel fringes).

## Mandatory Visual Inspection

**Never rank configs from numbers alone.** Always generate and inspect:
- A **1× native pixel strip** across all sizes (`12–16px`) and dark/blue/light surfaces (catches size jumps and subtle halo/bloom).
- A **3× or 4× nearest-neighbor zoomed crop** of stems (`HIIIllnnmm`) and diagonals (`wwvvkkxxzz`) (catches blotchy corners, broken counters, and color fringes).

## Wrap-Up

1. Verify `git status` is clean and `~/.config/fontlab/state.toml` was not modified.
2. Append verified findings and any newly ruled-out dead ends to `docs/research/experiments.md`.
