# Rendering Experiments

Benchmarks already run on this repo. Check this log before testing new settings, and append new results at the bottom.

## Ruled out

| Hypothesis / setting | Tested on | Measured outcome |
|---|---|---|
| ~~`antialias=rgb` in Chromium~~ **Overturned by Experiment 5** | Chromium 158 (Fontations), 5 surfaces | The old verdict scored chroma as a defect, but Windows Chrome's ClearType text has more chroma (`0.47`) than Linux `rgb` (`0.37`). Measured against real Windows captures, `rgb` + `slight` is about 2x closer than any grayscale config. The softer edges it showed come from Skia's wide LCD filter (see Experiment 5). |
| `hinting=full` or `medium` for matching Windows Chrome | Chromium 158 vs Windows Chrome 150 captures (2026-11-27) | Rounded advances and Skrifa bytecode put glyphs on different pixels than Windows: Segoe UI 14px L1 to Windows `16.4` (`rgb full`) and `19.3` (`grayscale medium`) vs `9.3` (`rgb slight`). Windows Chrome uses subpixel positioning, which only `slight` keeps on Linux. |
| Static `darkening >= 0.35` with `gamma >= 1.6` | Chromium 158 + Messenger dark/blue screenshot | Double-thickens `#ffffff` text on `#121723` dark navy and `#49659e` blue bubbles (`dblW 20.6–22.3%`, `bld3 40.2%`, `B 1.29–1.33x`), leaving chalky doubled white stems. |
| Waxweiler `gamma=1.8, contrast=0.0` + static `darkening 0.10–0.30` | Chromium 158, 5 surfaces | Because `darken.py` is static (unlike macOS dynamic darkening), light mode washes out (`phys L 0.87–0.90x`) while dark mode still blooms (`dblW 20.2–21.9%`). |
| `gamma >= 2.0` even at `darkening=0.00` | Chromium 158, `#000`/`#121723`/`#49659e` | Even with stock Inter 400 outlines, `dblW` hits `21.1%` at `g=2.0` and `24.2%` at `g=2.2` on dark and colored surfaces. |
| `ui_weight 475` or `500` with `hinting=slight` | Chromium 158, 12–16px Inter | Vertical stems reach `1.50–1.56px` at 14px without horizontal grid snapping, spilling across 3 pixel columns (`4-9-4`/`3-9-5`; `3px bleed 35–46%` vs `14%` stock) and looking fuzzy. |
| `hinting=full` on instanced `Inter 430 / 450 / 475` | Chromium 158, 12–16px | Uneven spacing and skinny stems at 14px. Only `w500` crosses Skrifa's 2px snap threshold, and `w500 full` causes `+22–37px` line-width jumps across sizes. |
| `small_bold` (`fontconfig embolden`) in Chromium or Qt | Chromium 158 (`13px` and `22px`), 2026-11-23 | `0` differing pixels in Chromium and Qt at every size; only GTK/Pango honors it. |
| Size-dependent weight via CSS `@font-face` or `darken.py` | Chromium 158, 2026-11-23 | `@font-face` cannot override `sans-serif`/`system-ui`/missing-family fallbacks, and static `ui_weight`/`darkening` thickens 22px titles by the same or larger percentage as 13px body text. Only a patched Skrifa darkener can scale by ppem. |
| `FREETYPE_PROPERTIES` in Chromium/Electron | Chromium 158 (>139) | Ignored since FreeType was removed (`FontationsLinuxSystemFonts` flag deleted). Still active in FreeType apps (Firefox, GTK, Qt and terminals). |
| `ui_weight 450` + `darkening >= 0.05`, or `gamma >= 1.3` at `ui_weight 450` | Chromium 158, 12–16px Inter (2026-11-26) | w450 stems measure ~1.45px at 14px; any added ink or edge brightening tips them over the 1.5px cliff: `bld3 44.4–50.4%` (vs 32–34% at w430) with 'm'/'n' counters closing. |
| Chromium `gamma > 1.2` (incl. Experiment 5's `g1.6`) | User's eye on screen, Brave, 2026-11-27 | Scored closest to the Windows screenshots by pixel L1, but on the real screen the user finds it awful: text "pops out" and looks 3D (reported several times). Not color fringes: with the box filter, fringe saturation is lower at `g1.6` than at `g1.2` on all surfaces. It shifts ink (dark-on-light heavier, light-on-dark thinner). Keep `gamma=1.2`. |
| `sf_weight 475` with `hinting=slight` | Chromium 158, 12–16px SF Pro Text (2026-11-26) | SF Pro Text 475 stems measure ~1.55px at 14px: `bld3 53–57%` 3-column bleed even at `g=1.2`. SF stays clean at 450 or below (28.1% at 14px). |
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

## Experiment 4 (2026-11-26): bolder-than-1.13x sweep, 28 configs (Chromium 158)

- **Setup**: Same 5 surfaces, 12–16px, isolated `FONTCONFIG_FILE` + `fontlab-text-shim.so`, `/usr/bin/chromium --headless=new` full-page screenshots (1000x920, `force-device-scale-factor=1`). Inter weights from `sources/inter/<w>` (Regular only), darkened via `builders/run.py darken` into a temp dir (`~/.cache/fontlab` untouched), SF Pro Text from `sources/sf/<w>`. Anchors re-measured first: `e1r1` (log rank 1) came out `1.13/1.12/1.07` and `bld3 32.3%` vs the log's `1.13/1.11/1.07, 32.1%`; `w500 full` `1.23/1.20/1.11` vs `1.25/1.21/1.13`. `dblW` below uses a wider pair definition (~1.45x the Exp2 numbers): the Exp2 20% "doubled stems" cliff is ~29% here.
- **Metrics**: as in Exp2, plus per-stem alpha column profiles (one row of the first 'H' stem) and mean isolated-stem footprint. Full harness: `bench/` scripts in the 2026-11-26 scratch session; report at `out/report.html` there.

### Findings

1. **The crisp ceiling at 14px/109 PPI grayscale is ~1.21x ink.** Past that, stems either widen to 3 columns (`bld3 >= 40%`) or saturate their 2 columns (alpha `0.93/0.76`), which is the chalky/doubled look. All crisp configs keep the same pixel *structure* as stock (2-column stems, pure-black gaps); only the column density rises (`0.80/0.59` stock -> `0.89/0.71` at 1.21x).
2. **At equal boldness near the cliff, darkening is safer than weight.** `w430 d0.25` (phys N 1.21, `bld3 33.8%`, dw 1) vs `w450 d0.15` (1.22, `bld3 45.1%`): w450's fatter base stems cross the cliff with any addition. Also `w430 d0.25 c0.6 g1.4` beats the live `w450 c0.4 g1.2` on every crispness metric while being +0.12x bolder.
3. **`contrast=0.8` is the cheap light-mode lever**: `w430 d0.25 c0.8 g1.4` lifts light-mode phys to 1.15 (from 1.09 at c0.6) with zero effect on dark-mode doubling.
4. **Real 2px stems exist only via `w500 + full`** (vS 0.67, bld3 3.0%): sharpest edges measured, but dw 8px (22–37px on long lines, per Exp2) and 'm'/'n' counters pinch shut — the autohinter trades counters for stem snap.
5. **SF Pro cannot go bold at 1x**: 475 bleeds (53–57%), and reaching 1.17x needs `g=1.6`, which thins light mode to 1.05x. SF at 450 stays the cleanest *mild* option.

### Top configs (all `antialias=grayscale`, `slight` unless noted)

| Rank | Font & weight | `darkening` | `hinting` | `c` / `g` | Phys (N / B / L) | dblW | bld3 | vS | dw | Notes |
|---:|---|---:|---|---|---|---:|---:|---:|---:|---|
| 1 | `inter 430` | `0.25` | `slight` | `0.8 / 1.4` | `1.21x / 1.19x / 1.15x` | 28.2% | 33.8% | 0.62 | 1px | Bolder sweet spot: e1r1's crispness with +0.08x ink, both modes lifted. |
| 2 | `inter 430` | `0.25` | `slight` | `0.6 / 1.3` | `1.18x / 1.16x / 1.13x` | 26.7% | 33.8% | 0.62 | 1px | Same font, 2.5 points less doubling. |
| 3 | `inter 430` | `0.35` | `slight` | `0.4 / 1.2` | `1.17x / 1.16x / 1.15x` | 26.2% | 33.8% | 0.63 | 1px | All boldness from outlines, gamma at Chromium's own; most uniform across surfaces. |
| 4 | `inter 500` | `0.00` | `full` | `0.2 / 1.2` | `1.23x / 1.20x / 1.11x` | 28.6% | 3.0%* | 0.67 | 8px | Hard 2px stems, zero fuzz; *'m' counters pinch, spacing jumps at some sizes (Exp2 rank 8). |
| 5 | `sf 450` | `0.00` | `slight` | `0.8 / 1.6` | `1.17x / 1.16x / 1.05x` | 28.1% | 28.1% | 0.62 | 1px | macOS family at its 1x limit; dark-mode-first (light mode stays thin). |

Dead ends confirmed this run (see Ruled out): `w450 + d>=0.05`, `w450 + g>=1.3`, `sf 475 slight`, `w400 d0.45 + g1.4` (gray wispy diagonals), and the stacked `w450 d0.50 c0.0 g1.4` preset (`personal_lucidglyph`: phys 1.34x but dblW 36.5%, bld3 51.1%, stems `0.93/0.76` — the chalky look).

## Experiment 5 (2026-11-27): matching real Windows Chrome captures (ClearType)

- **Reference**: Windows 11, Chrome 150, ClearType on (RGB, default gamma, tuner never run), same monitor (Gigabyte M27Q3, 1440p, RGB stripe, 100% scale). Lossless 1:1 captures of a 6-surface test page (`s1`..`s6`, `s6` = Reddit dark `#d7dadc` on `#1a1a1b`), rows Segoe UI 12–20, Inter 12–20, Arial, Consolas. Files: `/mnt/storage/Claude/Work/windows-text-captures` (README + HANDOFF there; harness, sweeps, renders and 8x montages in `linux-bench/`).
- **Linux side**: Chromium 158 headless, `force-device-scale-factor=1`, isolated `compare_setup()` with `preview_dir` redirected to scratch (live config untouched). Rows cut by their labels on both sides.
- **Metric**: per-row pixel L1 to the Windows crop (best of ±2px shifts, first 150px: `HIIIllnnmm wwvvkkxxzz`), linear-light ink relative to Windows, chroma relative to Windows. Dark = mean of `s1–s4, s6`; light = `s5`.

### Findings

1. **Windows Chrome text is subpixel ClearType with subpixel positioning.** Every stem shows color fringes (chroma `0.42–0.47`), and stems differ from each other by phase. Grayscale can't reproduce it: the best grayscale config (`web_fonts=windows`, `slight`, `c0.6 g1.4`) sits at L1 `15.1 / 17.9` on Segoe UI 14px.
2. **Handoff tests A and B both lose to plain `slight`.** A (`medium`, grayscale, `c1.0 g1.6`) L1 `19.4 / 23.5`; B (`full`, `rgb`, `c1.0 g1.6`) `16.7 / 20.4` and 26% too heavy in light mode. `rgb` + `slight` + `c0.2 g1.5`: `9.5 / 9.8`, ink `0.94x / 1.05x`.
3. **The remaining gap is Skia's LCD filter, not settings.** Fontations glyphs go through `SkScalerContext::GenerateImageFromPath` → `pack4xHToMask`: 4 samples per pixel and a 12-tap Gaussian per channel (sigma 5/3 sample). That is wider than ClearType's, so stem cores are softer and chroma lower (`0.37`). It is a compiled-in table (`uint32[36]`, found once in `/usr/lib/chromium/chromium` at file offset `0x27187c4`); no flag or fontconfig setting reaches it.
4. **A 1-pixel box filter matches Windows.** Patching that table in a scratch copy of the binary (`lcdpatch.py box4`: each channel averages the 4 samples of a 1px window centered on its subpixel, sum `0x110` like stock) plus `rgb slight c0.2 g1.6`:

| Row | Grayscale best | `rgb` stock filter | `rgb` + `box4` filter |
|---|---|---|---|
| Segoe UI 14 (L1 dark / light) | `15.1 / 17.9` | `9.5 / 9.8` | `7.2 / 8.2` (4-row mean) |
| Segoe UI 16 | `13.0 / 15.3` | `7.6 / 7.9` | `5.2 / 5.6` |
| Segoe UI 20 | `12.0 / 13.1` | `5.9 / 5.8` | `3.9 / 4.2` |
| Inter 16 | `14.4 / 16.7` | `6.8 / 7.4` | `4.4 / 5.5` |
| Consolas 14 | `13.6 / 15.3` | `8.3 / 8.4` | `5.7 / 6.4` |
| Ink vs Windows (dark / light) | `0.88 / 1.10` | `0.95 / 1.06` | `1.00 / 1.00` |
| Chroma (Windows `0.41–0.47`) | `0.01` | `0.36–0.39` | `0.42–0.47` |

   Narrower Gaussians (sigma `1.25`, `1.0`, `0.8`) and boxes `3.5`, `4.5`, `5`, `6` were all worse than `box4`. Inter and Segoe UI behave the same, so the fix is the rasterizer, not the font.
5. **The live config (Inter 430, `d0.25`, `c0.8 g1.4`, grayscale) is L1 `18.1 / 25.3` on Inter 14** and 28% heavier than Windows in light mode.

### Not yet verified

- ~~On-screen rendering~~ Checked by eye 2026-11-27 with `linux-bench/view.py` (real Wayland windows, `stock` vs `box4` copies, same settings): the user sees the difference, and `box4` loses the blur that the stock filter has.
- ~~How to ship the filter~~ Shipped as a runtime patch: `chromium_lcd_filter=box` (see below).

### Runtime patch from the shim (2026-11-27)

- `chromium/text-shim.c` `patch_lcd_filter()` finds the stock table in the read-only segments of the running executable (or `libcef.so`) and overwrites it in memory before `main()`. Exactly one hit in Chromium 158 (`0x27187c4`), Vesktop (`0x24b7b64`) and Spotify `libcef.so` (`0x2246a70`), each inside a plain `R` `PT_LOAD` segment.
- Headless renders of `s5`/`s6` (`web_fonts=windows`, `rgb`, `slight`, `c0.2 g1.6`) with stock `/usr/lib/chromium/chromium` + shim + `LCD_FILTER=box`: 0 differing pixels against the patched binary copy and against `renders/f-box4-c0.2-g1.6`. Shim with the stock filter: 2400–2900 pixels differ.
- Which process matters: patching only the zygote reproduces the full `box` render (renderers fork from it and rasterize glyphs). Patching only the browser, a renderer exec path, or the GPU process gives the stock render. Headless has no GPU process; with `--ozone-platform=headless` every process type, the GPU process included, maps the shim.
- Cost: the scan reads about 50 MB of the executable per exec'd process, about 12 ms with cold pages and 1 ms warm. 17-process Chromium: PSS 690–700 MB either way; summed RSS +75 MB (shared file pages counted per process).

## Experiment 6 (2026-11-27): native FreeType text vs Windows Explorer (DirectWrite ClearType)

- **Reference**: `explorer-c-windows.png` from the Experiment 5 capture set: Segoe UI 12px (9pt at 96 DPI), `#ffffff` on `#191919`, 16 words (names, dates, `File folder`). Word widths match Linux Segoe UI 12px within 1px; Segoe UI Variable does not match.
- **Linux side**: `pango-view` (cairo 1.18.6 + FreeType 2.15.0, the GTK3 path) with an isolated `FONTCONFIG_FILE` holding only the Windows fonts and one render rule. 72 configs: `rgba` none/rgb × `lcdfilter` × `hintstyle` none/slight/medium/full × `FREETYPE_PROPERTIES` (none, v35, stem darkening). Harness in `/mnt/storage/Claude/Work/windows-text-captures/linux-bench/native/`.

| Config | L1 to Explorer | Ink vs Windows | Chroma (Windows `0.34`) |
|---|---:|---:|---:|
| `rgb` + `lcdlight` + `hintfull` (or `medium`) | `14.6` | `0.98` | `0.40` |
| `rgb` + `lcddefault` + `hintfull` | `14.7` | `0.95` | `0.35` |
| `rgb` + `lcdlegacy` + `hintfull` | `18.3` | `1.14` | `0.50` |
| grayscale + `hintfull` (best grayscale) | `20.8` | `1.01` | `0` |
| `rgb` + `lcdlight` + `hintslight` | `22.3` | `0.84` | `0.37` |
| grayscale + `hintslight` (+ stem darkening, like live) | `27.2` (`28.0`) | `0.87` (`1.00`) | `0` |

### Findings

1. **Native text needs the opposite hinting from Chromium.** Explorer runs Segoe UI's own hints (full grid fit), so `hintfull`/`medium` with FreeType's v40 interpreter wins, while Chromium needs `slight` (Experiment 5). Stem darkening and v35 change nothing at `full` on a hinted TrueType font.
2. **FreeType's own LCD filters are already close to ClearType**: no patch needed on this path, unlike Skia's.
3. **Full hinting only helps fonts that carry bytecode** (Segoe UI, Arial, Consolas, Inter 400 static). On unhinted fonts (Inter 430/450 instances, Adwaita Sans) `full` falls back to the autohinter and distorts (see Ruled out).
4. **Toolkit limits**: GTK3, Qt widgets and foot honor `rgba`; GTK4/libadwaita renders grayscale only; Qt Quick `QtRendering` (distance fields, used by most of the Omarchy shell) ignores hinting and subpixel. Not yet measured on screen.

## Experiment 7 (2026-11-27): live Wayland windows vs the Windows captures, and why the desktop still felt wrong

- **Setup**: the live `state.toml` (rgb, slight, lcdlight, `chromium_lcd_filter=box`, `contrast=0.2`, `gamma=1.2`, `web_fonts=windows`, session shim), Hyprland 0.57.2, NVIDIA 620.73.04, M27Q3 at 2560x1440@320 scale 1.
- **Method**: real (non-headless) Chromium window on `textpage.html?s=s6`, captured with `grim`, rows cut by the same label scan as the Windows reference (`linux-bench/rows.py`), compared to `chrome-testpage-s6.png`.

### Findings

1. **A live Chromium window now matches Windows.** Row L1 on the dark surface: `segoe-12` 6.7, `segoe-13` 6.3, `segoe-14` 5.9, `segoe-16` 4.5, `inter-14` 6.2, `consolas-14` 5.0; ink 1.00x. (Rows that cut 1px off compare badly — 20-28 — so only trust rows whose band scan matched; the 8x montage agrees.) In other words the shim + fontconfig combination reaches Windows quality *in the framebuffer*.
2. **Half of a real page is not subpixel at all.** In the same live Brave window on x.com, text bands alternate between `mean chroma 0.00` (grayscale) and 25-55 (subpixel): the sidebar/nav/right rail are composited layers without an opaque background, so Chromium disables LCD text there (`WidgetBase::ComputeLCDTextPreference`, crbug 537814750, Won't Fix). Windows loses LCD text in the same places, but Chromium's Linux fallback is thinner: `SkSurfaceProps` carries one contrast/gamma for every mask format, so grayscale cannot get Windows' 2.2/1.0 while LCD keeps 1.2/0.2.
3. **Electron apps can be 100% grayscale.** The T3Code window measured `chroma 0.0` over its whole text area while a Chromium window on the same page measured 16-55: a transparent/rounded toplevel gives every layer a non-opaque background.
4. **Native text was the weakest surface, and it is a one-setting fix.** Reproduced Experiment 6 with `pango-view` against `zoom/explorer-filelist-1x.png` (Segoe UI 12px, white on `#191919`): `hintslight` + `lcdlight` renders visibly lighter and softer than Explorer, `hintfull`/`hintmedium` (identical in FreeType) matches it. The same holds for the unhinted Adwaita Sans and Inter at 13px: `full` is crisper with no distortion, so no per-family exception is needed. Chromium needs the opposite, so `hinting` (native, now `full`) and `chromium_hinting` (slight, written into `chromium-fonts.conf` after the render conf) are separate settings.
5. **Terminal**: `foot` + JetBrainsMono Nerd Font 12px goes from thin 1px-ish stems at `mono_hinting=slight` to solid 2px stems at `full`, with no change in the cell grid. Verified on screen (`foot/live.png`), not only in `pango-view`.

### Open: the display pipeline at 320Hz

The same monitor on Windows runs 144-240Hz; on Linux the mode is `2560x1440@320` (mode clock 1,289,060 kHz = 30.9 Gb/s at 8bpc, above DP 1.4's 25.92 Gb/s net, so **DSC is in use**; 240Hz at 992,250 kHz = 23.8 Gb/s is not). `modetest -c` also exposes `dithering mode: auto`, `NV_CONNECTOR_COLOR_FORMAT: auto`, `NV_CONNECTOR_OUTPUT_BPC: auto`, and the panel is 8bit+FRC. Whether DSC/FRC/temporal dithering soften 1px text on the glass (while `grim` still captures the clean framebuffer) is not measurable from inside the session: it needs an eye or a photo. Test by switching to 240Hz, then `dithering mode off`, then `render:cm_enabled false`.

## Experiment 8 (2026-11-28): do renderers need FONTCONFIG_FILE?

The shim and `chromium-env.sh` used to leave `FONTCONFIG_FILE=~/.config/fontlab/chromium-fonts.conf` in the environment, so every program an Electron app started (a terminal in an editor or in T3 Code) used Chromium's private fontconfig. The fix drops it from every child of the Chromium process (`child_env()` in `text-shim.c`). This checks that web pages still get the private rules.

- **Setup**: fake `HOME` with a `chromium-fonts.conf` that includes `/etc/fonts/fonts.conf` and maps the family `FontlabProbe` to `Liberation Mono` (strong prepend). `/opt/brave-origin-bin/brave --headless=new` (Chromium is not installed on this machine any more, so `/usr/bin/chromium` in the render-benchmark skill no longer exists). The page measures `ctx.measureText('iiiiiiiiii')` at `40px` in a canvas (renderer process) and reports to a local HTTP server.
- **Brave quirk**: headless Brave never loads the start URL and never exits on `--dump-dom` or `--screenshot`. Open the page with `--remote-debugging-port=9333` and `curl -X PUT "http://127.0.0.1:9333/json/new?<url>"`.

| shim | `FontlabProbe` | `Liberation Mono` | `sans-serif` |
|---|---|---|---|
| none | 111.1 (fallback) | 240.0 | 96.9 |
| old (env kept in children) | 240.0 | 240.0 | 96.9 |
| new (env dropped from children) | 240.0 | 240.0 | 96.9 |

### Findings

1. Renderers resolve families through the browser process (font IPC), so the variable is only needed in the process that loaded the shim. Dropping it from children changes nothing in pages.
2. A fake Chromium app (a copy of `sh` next to empty `icudtl.dat` and `resources.pak`) sees the variable itself, and its `execve` children do not. A `FONTCONFIG_FILE` the user set is passed on unchanged. This is now `ShimEnvironmentTest`.
