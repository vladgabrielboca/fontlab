# Rendering Experiments

Benchmarks already run on this repo. Check this log before testing new settings, and append new results at the bottom.

## Ruled out

| Hypothesis / setting | Tested on | Measured outcome |
|---|---|---|
| `antialias=rgb` in Chromium (any gamma `1.2–2.2`, `slight` or `full`) | Chromium 158 (Fontations), 5 surfaces | Heavy orange/cyan fringing (`chroma 0.155–0.176`, barely dropping from `0.173` at `g=1.2` to `0.159` at `g=1.8`) and softer luminance edges (`vSteep 0.48–0.53` vs `0.63` grayscale). Chromium ignores `lcdfilter`. Stick to `grayscale`. |
| Static `darkening >= 0.35` with `gamma >= 1.6` | Chromium 158 + Messenger dark/blue screenshot | Double-thickens `#ffffff` text on `#121723` dark navy and `#49659e` blue bubbles (`dblW 20.6–22.3%`, `bld3 40.2%`, `B 1.29–1.33x`), leaving chalky doubled white stems. |
| Waxweiler `gamma=1.8, contrast=0.0` + static `darkening 0.10–0.30` | Chromium 158, 5 surfaces | Because `darken.py` is static (unlike macOS dynamic darkening), light mode washes out (`phys L 0.87–0.90x`) while dark mode still blooms (`dblW 20.2–21.9%`). |
| `gamma >= 2.0` even at `darkening=0.00` | Chromium 158, `#000`/`#121723`/`#49659e` | Even with stock Inter 400 outlines, `dblW` hits `21.1%` at `g=2.0` and `24.2%` at `g=2.2` on dark and colored surfaces. |
| `ui_weight 475` or `500` with `hinting=slight` | Chromium 158, 12–16px Inter | Vertical stems reach `1.50–1.56px` at 14px without horizontal grid snapping, spilling across 3 pixel columns (`4-9-4`/`3-9-5`; `3px bleed 35–46%` vs `14%` stock) and looking fuzzy. |
| `hinting=full` on instanced `Inter 430 / 450 / 475` | Chromium 158, 12–16px | Uneven spacing and skinny stems at 14px. Only `w500` crosses Skrifa's 2px snap threshold, and `w500 full` causes `+22–37px` line-width jumps across sizes. |
| `small_bold` (`fontconfig embolden`) in Chromium or Qt | Chromium 158 (`13px` and `22px`), 2026-11-23 | `0` differing pixels in Chromium and Qt at every size; only GTK/Pango honors it. |
| Size-dependent weight via CSS `@font-face` or `darken.py` | Chromium 158, 2026-11-23 | `@font-face` cannot override `sans-serif`/`system-ui`/missing-family fallbacks, and static `ui_weight`/`darkening` thickens 22px titles by the same or larger percentage as 13px body text. Only a patched Skrifa darkener can scale by ppem. |
| `FREETYPE_PROPERTIES` in Chromium/Electron | Chromium 158 (>139) | Ignored since FreeType was removed (`FontationsLinuxSystemFonts` flag deleted). Still active in FreeType apps (Firefox, GTK, Qt and terminals). |
| Matching 2x/3x Retina Apple screenshots on 1x 109 PPI | 27" 1440p (`109 PPI`) vs `1206x1470` iPhone shot | The Retina shot has `51px` cap height and `6–7px` stems vs `~11px` and `1.3–1.5px` at 109 PPI. |

## Experiment 1 (2026-11-23): Google Search title weight flip (`google-sans-titles`)

- **Setup**: Headless Chromium 158 + CDP `CSS.getPlatformFontsForNode`, 30-site survey.
- **Finding**: Fresh address-bar Google searches omit the Google Sans `@font-face` and fall back to `sans-serif` (fontlab's heavier Inter), while in-page navigation loads Google's Google Sans webfont (~102% of stock Inter ink at 22px). Only Google sites flipped weight on the same titles.
- **Fix**: Added optional `googlesans` package (stock upstream `Google Sans Flex` variable font, no weights or darkening) plus `prepend+strong` aliases for `"Google Sans"`, `"Google Sans Text"`, and `"Google Sans Display"` in `70-fontlab-render.conf`, so they also work under `web_fonts=system` and `windows`. Verified `0` differing pixels at 400/500/700 against Google's web font.

## Experiment 2 (2026-11-25): Chromium 158 Fontations multi-surface sweep (340+ configs)

- **Environment**: Arch Linux, Hyprland, 27" 1440p `scale=1` (109 PPI), Chromium `158.0.8127.88` (Fontations + `fontlab-text-shim.so`), `12px–16px`.
- **Surfaces**: `#ffffff` on `#000000`, `#ffffff` on `#121723` (Messenger dark navy), `#e6e6e6` on `#24272e` (dark UI), `#ffffff` on `#49659e` (Messenger blue bubble), and `#1a1a1a` on `#ffffff` (light).
- **Metrics**: Physical linear-light ink weight (`sRGB -> linear` luminance relative to stock Linux `w400 d0.00 slight c0.2 g1.2 = 1.00x`), `dblW` (% adjacent horizontal pixel pairs both >=72% white on dark, catching glowing/doubled white stems), `bld3` (% vertical stems spanning >=3px), `vSteep`/`hSteep` edge steepness, `dw` (max width shift vs stock across 12–16px), plus 1x and 3x visual inspection on prose, stems (`HIIIllnnmm`), and diagonals (`wwvvkkxxzz`).

### Main takeaways

1. **Use one primary weight lever.** Pick mild `ui_weight=430` + `g=1.4`, or `w400` + `darkening 0.25–0.35` + `g=1.1–1.2`, or stock `w400 d0.00` + `c=1.0 g=1.6`. Combining two levers double-thickens dark mode.
2. **Under `slight` hinting, `darkening` blurs vertical stems less than `ui_weight` at equal ink.** `DARKEN_Y_EM = 1.25 * DARKEN_X_EM` puts more weight onto vertically-hinted horizontal strokes while leaving glyph advances unchanged (`dw = 0px`).
3. **True `wght=430` (`d=0.00`) stays below the 1.5px 3-column blur cliff** and keeps cleaner diagonal vertices (`w, v, k, x`) than `darken.py`.

### Top multi-surface configs (all `antialias=grayscale`)

| Rank | Archetype | Font & weight | `darkening` | `hinting` | `c` / `g` | Phys (Navy / Blue / Light) | dblW | bld3 | vS / hS | dw | Notes |
|---:|---|---|---:|---|---|---|---:|---:|---|---:|---|
| 1 | Android `g=1.4` + real `wght` | `inter 430` | `0.00` | `slight` | `0.6 / 1.4` | `1.13x / 1.11x / 1.07x` | 14.6% | 32.1% | 0.63 / 0.62 | 2px | Cleanest diagonals, real weight, zero bloom; applies to GTK/Qt too. |
| 2 | Linux `g=1.2` + darken | `inter 400` | `0.35` | `slight` | `0.4 / 1.2` | `1.14x / 1.17x / 1.14x` | 14.3% | 34.2% | 0.63 / 0.62 | 0px | Matched dark/light weight, no high-gamma feel, `dw=0`. |
| 3 | Windows `d=0` (capped) | `inter 400` | `0.00` | `slight` | `1.0 / 1.6` | `1.13x / 1.12x / 1.07x` | 15.9% | 29.2% | 0.64 / 0.64 | 0px | Lowest blur at `~1.13x`; stock Inter 400 (Chromium-only effect). |
| 4 | Moderate `g=1.4` + light darken | `inter 400` | `0.25` | `slight` | `0.4 / 1.4` | `1.15x / 1.13x / 1.05x` | 15.7% | 32.5% | 0.62 / 0.61 | 0px | Zero-drift sibling of #1. |
| 5 | Zero-shim Linux default | `inter 400` | `0.25` | `slight` | `0.2 / 1.2` | `1.08x / 1.07x / 1.05x` | 13.3% | 30.0% | 0.63 / 0.62 | 0px | No shim needed; Chromium matches native GTK/Qt and Flatpaks. |
| 6 | Pure moderate gamma | `inter 400` | `0.00` | `slight` | `0.6 / 1.4` | `1.07x / 1.06x / 1.03x` | 13.5% | 27.4% | 0.63 / 0.62 | 0px | Subtle, crisp step up from stock. |
| 7 | macOS font family | `sf 450` | `0.00` | `slight` | `0.4 / 1.4` | `1.12x / 1.11x / 1.03x` | 15.3% | 32.3% | 0.63 / 0.62 | 0px | Best non-Inter option (`sf_weight=450`). |
| 8 | Skrifa 2px full autohint | `inter 500` | `0.00` | `full` | `0.2 / 1.2` | `1.25x / 1.21x / 1.13x` | 19.5% | 29.7% | 0.67 / 0.62 | 22px | Hard 2px snapped stems at 14–16px, zero shim; wide tracking jump (`+22–37px`). |

## Experiment 3 (2026-11-25): Firefox 161 (FreeType) vs. Chromium 158 (Fontations) pixel twins

- **Setup**: Rendered the same 5-surface Inter 400 page in headless Firefox `161.0` (`layout.css.devPixelsPerPx=1.0`, `MOZ_DISABLE_CONTENT_SANDBOX=1`) across 4 `FREETYPE_PROPERTIES` modes, then matched each against all 167 Chromium Fontations renders by minimum pixel-aligned L1 distance.
- **Finding**: FreeType's `all` and `strong` (lucidglyph) stem darkening are subtler than expected (`+3%–8%` dark, `+8%–12%` light vs stock Chromium) because Firefox/Cairo blends at `gamma=1.0` while Chromium defaults to `gamma=1.2`. Chromium Fontations can match FreeType closely (`L1 3.1–3.7 / 255`):

| Firefox (FreeType) reference | FF phys (N / B / L) | FF dblW / bld3 | Closest Chromium (Fontations) twin | Twin phys (N / B / L) | Pixel L1 |
|---|---|---:|---|---:|---:|
| FreeType `off` (stock FT) | `0.92x / 0.93x / 1.01x` | `9.7% / 23.2%` | `w400 d0.00 slight c0.2 g1.0` | `0.94x / 0.94x / 1.05x` | n/a |
| FreeType `all` (`cff` + `autofitter`) | `1.03x / 1.03x / 1.08x` | `11.7% / 32.2%` | `w400 d0.25 slight c0.2 g1.1` *(or `c0.0 g1.0`)* | `1.04x / 1.04x / 1.08x` | 3.24 |
| FreeType `strong` (lucidglyph) | `1.08x / 1.07x / 1.12x` | `13.2% / 35.3%` | `w430 d0.00 slight c0.4 g1.2` or `w400 d0.25 slight c0.4 g1.2` | `1.06–1.08x / 1.05–1.07x / 1.08–1.09x` | 3.74 |
| FreeType `v35 + full` (classic BCI) | `0.96x / 0.93x / 1.02x` | `10.4% / 21.4%` | `w400 d0.00 full` *(Inter 400 native v40 bytecode)* | `1.02x / 1.01x / 1.03x` | 5.14 |

## Adding new entries

Include these details when logging a new run:

1. Date, browser/engine versions, monitor scale/PPI, and surfaces/sizes tested.
2. Exact settings compared, including a stock baseline.
3. Both pixel metrics and visual notes from inspecting the PNGs.
4. Any dead ends added to the "Ruled out" table at the top.
