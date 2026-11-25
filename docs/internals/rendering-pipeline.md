# Linux / Chromium / Fontations Rendering Pipeline

Technical ground truth verified from upstream Chromium, Skia, Fontations/Skrifa, and FreeType source code and docs. Read this before proposing new settings, tuning defaults, or debugging rendering discrepancies.

## 1. Why Chromium/Electron Changed (Fontations vs. FreeType)

- **FreeType is permanently removed from Chromium/Blink** after `139.0.7258` (`--disable-features=FontationsLinuxSystemFonts` was deleted in commit `2fc1ae19`; see [fontations#1496 comment 3004330901](https://github.com/googlefonts/fontations/pull/1496#issuecomment-3004330901) and `crbug.com/349952802`).
- **`FREETYPE_PROPERTIES` has zero effect in Chromium or Electron** (`issuetracker.google.com/issues/415076053` closed `WontFix`). Neither `autofitter:no-stem-darkening=0` / `cff:no-stem-darkening=0` nor `truetype:interpreter-version=35` reaches Chromium/Fontations. They still apply to FreeType apps (Firefox, GTK, Qt, terminals).
- **Skrifa has no stem darkening** ([fontations#1407](https://github.com/googlefonts/fontations/issues/1407)). Nikolaus Waxweiler (`madig`) also notes there that FreeType's autohinter stem darkening (`FT_Outline_Embolden`, the algorithm in `fontlab/builders/darken.py`) is inferior to Adobe's CFF stem darkener because true stem darkening should preserve vertical grid fitting and taper off as pixel size grows.
- **Static `.ttf` darkening vs. runtime stem darkening**: `fontlab`'s `darkening` is baked statically into the font outline, so it expands strokes by a fixed em at **all** pixel sizes and on **both** light-on-dark and dark-on-light text equally (unlike FreeType/CoreText dynamic darkening, which tapers at larger ppem and behaves differently across polarities).

## 2. Exact Skia `SkMaskGamma` Math (`--text-contrast` & `--text-gamma`)

From upstream Skia `src/core/SkMaskGamma.cpp` (`SkTMaskGamma_build_correcting_lut`) and Chromium `skia/BUILD.gn`:

### Upstream Chromium Platform Defaults (`skia/BUILD.gn`)

| Platform | `SK_GAMMA_EXPONENT` | `SK_GAMMA_CONTRAST` | Notes |
|---|---:|---:|---|
| **Linux / ChromeOS** | `1.2` | `0.2` | Hardcoded compromise; causes thin dark-mode text ([crbug/40267453](https://issues.chromium.org/issues/40267453)). |
| **Android** | `1.4` | `0.0` | Plus `SK_GAMMA_APPLY_TO_A8`. |
| **macOS** | `sRGB` (~`2.2`) | `0.0` | Relies on CoreGraphics dynamic stem darkening. |
| **Windows** | `sRGB` (~`2.2`) | `1.0` *(ClearType `0.5–1.0`)* | Uses `contrast` (not static darkening) to recover black-on-white weight. |

### Exact LUT Behavior (`SkMaskGamma.cpp`)

For a foreground channel luminance `src` in `[0, 1]`:

```cpp
const float dst = 1.0f - src;                         // Skia GUESSES the background!
const float linDst = dstConvert.toLuma(dstGamma, dst);
const float adjustedContrast = contrast * linDst;     // Tapers to 0 for white text!
float srca = rawSrca + (1.0f - rawSrca) * adjustedContrast * rawSrca;
float linOut = linSrc * srca + (1.0f - srca) * linDst;
float out = dstConvert.fromLuma(dstGamma, linOut);
float result = (out - dst) / (src - dst);
```

Four critical consequences:

1. **`contrast` ONLY affects dark text on light backgrounds.** When `src = 1.0` (white text `#ffffff`), `dst = 0.0`, `linDst = 0.0`, so `adjustedContrast = 0.0`. Raising `contrast` never changes `#ffffff` text on dark backgrounds.
2. **`gamma` affects dark and light in opposite directions.**
   - **White on dark (`src = 1, dst = 0`)**: `result = rawSrca^(1 / gamma)`. Higher `gamma` pushes partial edge coverage **upward** toward white (`0.50 → 0.56` at `1.2`, `0.65` at `1.6`, `0.68` at `1.8`, `0.73` at `2.2`).
   - **Black on white (`src = 0, dst = 1`)**: `result = 1 - (1 - srca)^(1 / gamma)`. Higher `gamma` **thins** black-on-white (`0.50 → 0.32` at `1.8` when `contrast = 0`), requiring `contrast` (or darkening) to restore weight.
3. **Skia guesses `dst = 1.0 - src`.** On a colored surface like Messenger's blue bubble (`#49659e`) with white text (`#ffffff`), Skia still assumes a pure black `#000` background, over-brightening white edges when `gamma` is high.
4. **Never double-stack static `darkening` + high `gamma` on dark mode.** High `gamma` already thickens white-on-dark; adding baked `.ttf` `darkening` thickens white-on-dark a *second* time, producing glowing, chalky, "doubled" white stems (`dblW > 20%`).

## 3. Exact Fontations Hinting & Rasterization (`SkTypeface_fontations.cpp`)

From upstream Skia `src/ports/SkTypeface_fontations.cpp`:

- **Grayscale collapses `full` → `normal`**: `if (kFull == h && !isLCD(*rec)) h = kNormal;`. Only RGB LCD mode (`isLCD`) invokes Skrifa with `do_lcd_antialiasing = true`.
- **`kSlight`**: Forces `AutoHinting::ForceForGlyf` with `do_light_hinting = true` (vertical-only snapping) and **linear (unrounded) metrics** (`fDoLinearMetrics = true`), preserving horizontal spacing.
- **`kNormal` / `kFull`**: Uses `AutoHinting::Fallback` and **rounds advances to integers** (`roundf(adjusted_advance)`):
  - Fonts **with** TrueType bytecode (`Inter 400`, `Roboto 400–500`, `Segoe UI`) run Skrifa's TrueType v40 bytecode interpreter.
  - Fonts **without** bytecode (`Inter 430–500`, `Adwaita Sans`) fall back to Skrifa's full autohinter (horizontal + vertical snapping).
- **No Fontconfig `lcdfilter` in Chromium**: Fontations outputs paths to Skia's `GenerateImageFromPath()`, which uses Skia's internal LCD filter and ignores Fontconfig's `lcdfilter`.
- **No Fontconfig `embolden` (`small_bold`) in Chromium or Qt**: Chromium and Qt ignore `embolden` at all sizes; only GTK/Pango honors it.

## 4. Physical Display Limits (109 PPI vs. HiDPI Retina)

Per FreeType's [Text Rendering General](https://freetype.org/freetype2/docs/hinting/text-rendering-general.html):
- On a 1× 27" 1440p monitor (`109 PPI`), 14–15px UI text has ~11px cap height and **1.30–1.56px** vertical stems. Once a vertical stem approaches ~`1.50px` without horizontal grid-snapping (`slight`), subpixel X positions spill across **3 pixel columns** (`4-9-4` / `3-9-5` halos), which looks fuzzy.
- On a 2× Retina Mac (220–254 PPI) or 3× iPhone (460 PPI), the same UI label has **3 to 7 solid physical pixels per stem**, so antialiased fringes are <15% of stroke width. That gap is hardware PPI, not a software fontconfig setting.

## 5. Primary Sources

- [FreeType: On Slight Hinting, Proper Text Rendering, Stem Darkening and LCD Filters](https://freetype.org/freetype2/docs/hinting/text-rendering-general.html)
- [Fontations #1407 — Support stem darkening for CFF driver and when autohinting](https://github.com/googlefonts/fontations/issues/1407)
- [Fontations PR #1496 — `[skrifa]` support interpreter-version 35](https://github.com/googlefonts/fontations/pull/1496#issuecomment-3004330901)
- [Chromium #40267453 — Wrong gamma correction value to Skia on Linux](https://issues.chromium.org/issues/40267453)
- [Arch Wiki — Font configuration](https://wiki.archlinux.org/title/Font_configuration)
- Upstream source inspected: `google/skia` (`src/core/SkMaskGamma.h`, `src/core/SkMaskGamma.cpp`, `src/core/SkScalerContext.cpp`, `src/ports/SkTypeface_fontations.cpp`) and `chromium/chromium` (`skia/BUILD.gn`, `skia/ext/legacy_display_globals.cc`, `ui/gfx/font_render_params_linux.cc`).
