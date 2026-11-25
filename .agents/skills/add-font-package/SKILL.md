---
name: add-font-package
description: Add or modify a font package, weight/darkening builder, or rendering setting in fontlab. Use when adding a new font family, changing fontconfig alias rules, updating Chromium private fontconfig, or adding a setting to settings.py.
---

# Adding or Modifying a Font Package or Setting

Follow every layer cleanly so CLI, TUI, `apply()`, `preview.compare_setup()`, `availability.Context`, and tests stay in sync.

## Checklist: Adding a Font Package

1. **Builder (`fontlab/builders/weights.py` & `fontlab/builders/run.py`)** *(if instancing weights)*:
   - Keep `fontlab/builders/` strictly independent of `fontlab.*` (runs under a separate Python that has `fontTools`).
   - Strip `STAT` and `avar` tables on static instances, set `OS/2.usWeightClass`, `OS/2.fsSelection`, `head.macStyle`, and `name` IDs (`1, 2, 4, 6, 16, 17`) so apps see heavier Regular/Italic as normal weight `400`.
   - Note whether the source font has TrueType hinting tables (`fpgm`, `prep`, `cvt `, `gasp`)—if outlines are modified without valid instructions (like `jetbrains_mono`), strip bytecode tables and per-glyph programs cleanly.
   - Register the command in `builders/run.py` (`nfixed` and `builder` maps).

2. **Package (`fontlab/packages.py`)**:
   - Subclass `Package` with `id`, `name`, `summary`, `optional`, and optional `license_note` / `needs_folder`.
   - Pin downloads with SHA-256 hashes (via `download.fetch(..., sha256)`).
   - Populate `Manifest(version, weights, replaces)`: `replaces` lists system font paths found via `find_fonts()` (which excludes `paths.P.installed_fonts`) so `70-fontlab-render.conf` hides them via `<rejectfont>`.
   - Append to `PACKAGES` (which populates `BY_ID`). Remember `Package.install()` automatically marks staged files `0o444` and swaps atomically via `replace_dir()`.

3. **Family & Darkening (`fontlab/fonts.py`)**:
   - Add a `Family(package, weight_key, darkens=..., system_base=...)` entry to `FAMILIES`.
   - Set `darkens=True` **only** for TrueType (`glyf`) outlines (`darken.py` skips variable fonts with `fvar` and only transforms `glyf` contours, not `CFF`).

4. **Fontconfig & Chromium (`fontlab/fontconfig.py` & `fontlab/chromium.py`)**:
   - Use `mode="prepend" binding="strong"` for all family aliases (Chromium ignores weak matches).
   - Decide whether aliases belong in `70-fontlab-render.conf` (applies everywhere, including `web_fonts=system` and Chromium's `windows` private conf—like `googlesans`) or `71-fontlab-web.conf` (only when `web_fonts` selects it).
   - If the package affects `web_fonts` or `system-ui`, update `chromium.SYSTEM_UI` / `chromium.fonts_conf()` and `preview.compare_setup()`.

5. **Availability & Settings (`fontlab/availability.py` & `fontlab/settings.py`)**:
   - Update `WEIGHT_PACKAGES`, `CHOICE_PACKAGES`, and `Setting.needs` so unavailable options grey out in the TUI, are rejected by `fontlab set`, and gracefully fall back in `Context.effective()`.
   - If adding a new setting in `settings.py`, ensure every choice is a string in a fixed tuple, default is in `choices`, and `state.normalize()` handles any numeric formatting.

6. **Tests & Docs (`tests/test_fontlab.py`, `README.md`)**:
   - Add unit tests covering: package install/remove atomicity, `fonts.plan()`/`install()` key caching, generated fontconfig XML (`render_conf` / `web_conf`), `Context.effective()` fallback when uninstalled, and `preview.compare_setup()`.
   - Update the package/settings tables and credits in `README.md` (and `docs/internals/architecture.md` if paths or pipeline stages changed).

## Verification

```bash
python3 -m unittest discover -s tests -v
```

If the change affects rendered glyphs or aliases in Chromium:
- Verify `fc-match "<Family>"` and `fc-match "<Family>:weight=500"` resolve to `~/.local/share/fonts/fontlab/...`.
- Use `.agents/skills/render-benchmark/SKILL.md` to verify actual Chromium pixels in isolation before committing.
