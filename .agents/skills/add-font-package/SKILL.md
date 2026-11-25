---
name: add-font-package
description: Add or modify a font package, weight/darkening builder, or rendering setting in fontlab. Use when adding a new font family, changing fontconfig alias rules, updating Chromium private fontconfig, or adding a setting to settings.py.
---

# Adding or Modifying a Font Package or Setting

Update every layer below so CLI, TUI, `apply()`, `preview.compare_setup()`, `availability.Context`, and tests stay in sync.

## Checklist

1. **Builder (`fontlab/builders/weights.py` and `fontlab/builders/run.py`)** *(if instancing weights)*:
   - Keep `fontlab/builders/` independent of `fontlab.*` (it runs under whichever Python has `fontTools`).
   - Strip `STAT` and `avar` tables on static instances. Set `OS/2.usWeightClass`, `OS/2.fsSelection`, `head.macStyle`, and `name` IDs (`1, 2, 4, 6, 16, 17`) so apps treat heavier Regular/Italic builds as weight `400`.
   - Check whether the source has TrueType hinting tables (`fpgm`, `prep`, `cvt `, `gasp`). If outlines change without matching instructions (as in `jetbrains_mono`), strip those tables and the per-glyph programs.
   - Register the builder command in `builders/run.py` (`nfixed` and `builder` maps).

2. **Package (`fontlab/packages.py`)**:
   - Subclass `Package` with `id`, `name`, `summary`, `optional`, and `license_note` / `needs_folder` if needed.
   - Pin downloads with SHA-256 hashes via `download.fetch(..., sha256)`.
   - Populate `Manifest(version, weights, replaces)`. `replaces` lists system font paths from `find_fonts()` (which excludes `paths.P.installed_fonts`) so `70-fontlab-render.conf` hides them with `<rejectfont>`.
   - Append to `PACKAGES` (which builds `BY_ID`). `Package.install()` marks staged files `0o444` and swaps atomically via `replace_dir()`.

3. **Family and darkening (`fontlab/fonts.py`)**:
   - Add a `Family(package, weight_key, darkens=..., system_base=...)` entry to `FAMILIES`.
   - Set `darkens=True` only for TrueType (`glyf`) outlines. `darken.py` skips variable fonts (`fvar`) and only transforms `glyf` contours, not `CFF`.

4. **Fontconfig and Chromium (`fontlab/fontconfig.py` and `fontlab/chromium.py`)**:
   - Use `mode="prepend" binding="strong"` for all family aliases (Chromium ignores weak matches).
   - Put global aliases in `70-fontlab-render.conf` (applies under `web_fonts=system` and Chromium's `windows` private conf, like `googlesans`), and web-font-only aliases in `71-fontlab-web.conf`.
   - If the package affects `web_fonts` or `system-ui`, update `chromium.SYSTEM_UI`, `chromium.fonts_conf()`, and `preview.compare_setup()`.

5. **Availability and settings (`fontlab/availability.py` and `fontlab/settings.py`)**:
   - Update `WEIGHT_PACKAGES`, `CHOICE_PACKAGES`, and `Setting.needs` so missing packages grey out choices in the TUI, fail in `fontlab set`, and fall back to defaults in `Context.effective()`.
   - New settings in `settings.py` need a fixed tuple of string choices, a default inside `choices`, and any numeric normalization handled in `state.normalize()`.

6. **Tests and docs (`tests/test_fontlab.py`, `README.md`)**:
   - Add unit tests for install/remove atomicity, `fonts.plan()`/`install()` caching, generated fontconfig XML (`render_conf` / `web_conf`), `Context.effective()` fallback when uninstalled, and `preview.compare_setup()`.
   - Update the tables and credits in `README.md` (plus `docs/internals/architecture.md` if paths or `apply()` stages changed).

## Verification

```bash
python3 -m unittest discover -s tests -v
```

When a change affects rendered glyphs or aliases in Chromium:

- Check that `fc-match "<Family>"` and `fc-match "<Family>:weight=500"` resolve to `~/.local/share/fonts/fontlab/...`.
- Run `.agents/skills/render-benchmark/SKILL.md` to verify Chromium pixels in isolation before committing.
