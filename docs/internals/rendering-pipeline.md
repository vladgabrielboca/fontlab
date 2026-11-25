# Linux / Chromium / Fontations Rendering Pipeline

Notes from upstream Chromium, Skia, Fontations/Skrifa, and FreeType source code. Check these limits before adding a setting or changing defaults.

## Fontations vs. FreeType in Chromium

- **FreeType is gone from Chromium/Blink** after `139.0.7258`. Commit `2fc1ae19` deleted `--disable-features=FontationsLinuxSystemFonts` (see [fontations#1496 comment 3004330901](https://github.com/googlefonts/fontations/pull/1496#issuecomment-3004330901) and `crbug.com/349952802`).
- **`FREETYPE_PROPERTIES` does nothing in Chromium or Electron** (`issuetracker.google.com/issues/415076053`, closed `WontFix`). Neither `autofitter:no-stem-darkening=0` / `cff:no-stem-darkening=0` nor `truetype:interpreter-version=35` reaches Fontations. They still apply to FreeType apps (Firefox, GTK, Qt and terminals).
- **Skrifa has no stem darkening** ([fontations#1407](https://github.com/googlefonts/fontations/issues/1407)). In that issue, Nikolaus Waxweiler (`madig`) notes that FreeType's autohinter stem darkening (`FT_Outline_Embolden`, the algorithm ported in `fontlab/builders/darken.py`) is weaker than Adobe's CFF stem darkener because runtime darkening should preserve vertical grid fitting and taper off at larger pixel sizes.
- **Static `.ttf` darkening vs. runtime darkening**: `fontlab`'s `darkening` is baked into the font outlines, so it thickens strokes by a fixed em at every pixel size and on both light and dark backgrounds equally. FreeType and CoreText taper darkening down as ppem grows.

## Skia `SkMaskGamma` (`--text-contrast` and `--text-gamma`)

From Skia `src/core/SkMaskGamma.cpp` (`SkTMaskGamma_build_correcting_lut`) and Chromium `skia/BUILD.gn`:

### Platform defaults in `skia/BUILD.gn`

| Platform | `SK_GAMMA_EXPONENT` | `SK_GAMMA_CONTRAST` | Notes |
|---|---:|---:|---|
| Linux / ChromeOS | `1.2` | `0.2` | Hardcoded compromise; produces thin dark-mode text ([crbug/40267453](https://issues.chromium.org/issues/40267453)). |
| Android | `1.4` | `0.0` | Plus `SK_GAMMA_APPLY_TO_A8`. |
| macOS | `sRGB` (~`2.2`) | `0.0` | Paired with CoreGraphics dynamic stem darkening. |
| Windows | `sRGB` (~`2.2`) | `1.0` *(ClearType `0.5–1.0`)* | Uses `contrast` to recover black-on-white weight. |

### LUT math (`SkMaskGamma.cpp`)

For a foreground channel luminance `src` in `[0, 1]`:

```cpp
const float dst = 1.0f - src;                         // Skia guesses the background
const float linDst = dstConvert.toLuma(dstGamma, dst);
const float adjustedContrast = contrast * linDst;     // Tapers to 0 for white text
float srca = rawSrca + (1.0f - rawSrca) * adjustedContrast * rawSrca;
float linOut = linSrc * srca + (1.0f - srca) * linDst;
float out = dstConvert.fromLuma(dstGamma, linOut);
float result = (out - dst) / (src - dst);
```

What this means in practice:

1. **`contrast` only changes dark text on light backgrounds.** When `src = 1.0` (`#ffffff` text), `dst = 0.0` and `linDst = 0.0`, so `adjustedContrast` is `0.0`. Raising `contrast` never alters pure white text on dark backgrounds.
2. **`gamma` pushes dark and light modes in opposite directions.**
   - White on dark (`src = 1, dst = 0`): `result = rawSrca^(1 / gamma)`. Higher `gamma` lifts partial edge coverage toward white (`0.50 -> 0.56` at `1.2`, `0.65` at `1.6`, `0.68` at `1.8`, `0.73` at `2.2`).
   - Black on white (`src = 0, dst = 1`): `result = 1 - (1 - srca)^(1 / gamma)`. Higher `gamma` thins black-on-white (`0.50 -> 0.32` at `1.8` when `contrast = 0`), so light mode needs `contrast` (or darkening) to keep weight.
3. **Skia guesses `dst = 1.0 - src`.** On a colored surface like Messenger's blue bubble (`#49659e`) with white text (`#ffffff`), Skia still assumes `#000` behind the text, which over-brightens edges at high `gamma`.
4. **Stacking static `darkening` with high `gamma` over-thickens dark mode.** High `gamma` already boosts white-on-dark coverage; adding baked `.ttf` `darkening` thickens it again, leading to glowing, doubled white stems (`dblW > 20%`).

## Fontations hinting (`SkTypeface_fontations.cpp`)

From Skia `src/ports/SkTypeface_fontations.cpp`:

- **Grayscale collapses `full` to `normal`**: `if (kFull == h && !isLCD(*rec)) h = kNormal;`. Only RGB LCD mode (`isLCD`) passes `do_lcd_antialiasing = true` to Skrifa.
- **`kSlight`**: Forces `AutoHinting::ForceForGlyf` with `do_light_hinting = true` (vertical snapping only) and linear, unrounded metrics (`fDoLinearMetrics = true`), keeping horizontal spacing intact.
- **`kNormal` and `kFull`**: Uses `AutoHinting::Fallback` and rounds glyph advances to integers (`roundf(adjusted_advance)`):
  - Fonts with TrueType bytecode (`Inter 400`, `Roboto 400–500`, `Segoe UI`) run Skrifa's TrueType v40 bytecode interpreter.
  - Fonts without bytecode (`Inter 430–500`, `Adwaita Sans`) fall back to Skrifa's full autohinter (horizontal and vertical snapping).
- **Fontconfig `lcdfilter` is ignored in Chromium**: Fontations outputs paths to Skia's `GenerateImageFromPath()`, which uses Skia's own LCD filter.
- **Fontconfig `embolden` (`small_bold`) is ignored in Chromium and Qt**: Only GTK/Pango honors it.

## Display density limits (109 PPI vs. HiDPI)

Per FreeType's [Text Rendering General](https://freetype.org/freetype2/docs/hinting/text-rendering-general.html):

- On a 1x 27" 1440p monitor (`109 PPI`), 14–15px UI text has ~11px cap height and `1.30–1.56px` vertical stems. Once a vertical stem nears `1.50px` without horizontal grid snapping (`slight`), subpixel X positions spill across 3 pixel columns (`4-9-4` / `3-9-5` halos) and look fuzzy.
- On a 2x Retina Mac (220–254 PPI) or 3x iPhone (460 PPI), the same UI label spans 3 to 7 solid physical pixels per stem, so antialiasing fringes stay under 15% of stroke width. Fontconfig settings cannot close a 2x–4x pixel-density gap.

## Sources

- [FreeType: On Slight Hinting, Proper Text Rendering, Stem Darkening and LCD Filters](https://freetype.org/freetype2/docs/hinting/text-rendering-general.html)
- [Fontations #1407: Support stem darkening for CFF driver and when autohinting](https://github.com/googlefonts/fontations/issues/1407)
- [Fontations PR #1496: `[skrifa]` support interpreter-version 35](https://github.com/googlefonts/fontations/pull/1496#issuecomment-3004330901)
- [Chromium #40267453: Wrong gamma correction value to Skia on Linux](https://issues.chromium.org/issues/40267453)
- [Arch Wiki: Font configuration](https://wiki.archlinux.org/title/Font_configuration)
- Upstream files checked: `google/skia` (`src/core/SkMaskGamma.h`, `src/core/SkMaskGamma.cpp`, `src/core/SkScalerContext.cpp`, `src/ports/SkTypeface_fontations.cpp`) and `chromium/chromium` (`skia/BUILD.gn`, `skia/ext/legacy_display_globals.cc`, `ui/gfx/font_render_params_linux.cc`).
