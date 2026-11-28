---
name: add-font-package
description: Add or modify a font package, weight/darkening builder, or rendering setting in fontlab. Use when adding a new font family, changing fontconfig alias rules, updating Chromium private fontconfig, or adding a setting to settings.py.
---

# Adding or Modifying a Font Package or Setting

Update every layer below so CLI, TUI, `apply()`, `preview.compare_setup()`, `availability.Context`, and tests stay in sync.

## Checklist

1. **Builder (`fontlab/builders/weights.py` and `fontlab/builders/run.py`)** *(only for a new build method)*:
   - Keep `fontlab/builders/` independent of `fontlab.*` (it runs under whichever Python has `fontTools`).
   - Strip `STAT` and `avar` tables on static instances. Set `OS/2.usWeightClass`, `OS/2.fsSelection`, `head.macStyle`, and `name` IDs (`1, 2, 4, 6, 16, 17`) so apps treat heavier Regular/Italic builds as weight `400`.
   - Check whether the source has TrueType hinting tables (`fpgm`, `prep`, `cvt `, `gasp`). If outlines change without matching instructions (as in `jetbrains_mono`), strip those tables and the per-glyph programs.
   - Most packages need no builder code: `Package.weight_faces()` returns `WeightFace(base, variable, method, axes)` entries and `weights.at_weight()` handles `instance` and `graft`. A new method goes in `at_weight()`.
   - Bump `fonts.BUILDER_VERSION` when a builder's output changes; cached builds are then made again on the next apply.

2. **Package (`fontlab/packages.py`)**:
   - Subclass `Package` with `id`, `name`, `summary`, `optional`, and `license_note` if needed.
   - Set how `fonts.py` installs it: `weight_key` (the setting that picks its weight), `darkens=True` only for TrueType (`glyf`) outlines (`darken.py` skips variable fonts and `CFF`), `installs=False` when it is not a desktop font (Windows fonts).
   - Override `install_sources()` when it is not a plain download (imported from a folder with `ask=True`, detected folders). The TUI and CLI only render that list.
   - These attributes are the only place package-to-setting links live: `availability.needs()`, `unlocking()`, `unlocks()` (Fonts tab) and `fonts.families()` derive from them.
   - Pin downloads with SHA-256 hashes via `download.fetch(..., sha256)`.
   - `build()` only fetches stock files: the family into `400/` (leave it out when the system font is the 400 base), variable fonts into `variable/` (list them in `VARIABLE`). Return `Manifest(version)`.
   - Override `replaces()` to list the system font paths it stands in for, from `find_fonts()` (which excludes `paths.P.installed_fonts`), so `70-fontlab-render.conf` hides them with `<rejectfont>`. It runs at every apply.
   - Append to `PACKAGES` (which builds `BY_ID`). `Package.install()` marks staged files `0o444` and swaps atomically via `replace_dir()`.

3. **Fontconfig and Chromium (`fontlab/fontconfig.py` and `fontlab/chromium.py`)**:
   - Use `mode="prepend" binding="strong"` for all family aliases (Chromium ignores weak matches).
   - Put global aliases in `70-fontlab-render.conf` (applies under `web_fonts=system` and Chromium's `windows` private conf, like `googlesans`), and web-font-only aliases in `71-fontlab-web.conf`.
   - A new `web_fonts` choice is one `WebFont(family, system_ui, package)` entry in `settings.WEB_FONTS`; `fontconfig.web_conf()`, `chromium.system_ui_rule()` and availability read it. Apply and the comparison window both get their fontconfig text from `fontconfig.confs()`.

4. **Settings (`fontlab/settings.py`)**:
   - A new setting needs a fixed tuple of string choices, a default inside `choices`, `help` (what the choices do) and `affects` (which apps, and what it takes to see a change). Numeric normalization goes in `state.normalize()`.
   - `needs=("shim",)` or `("vencord",)` for non-package needs.
   - `active_when=((key, values),)` when it does nothing unless another setting has one of `values`. Locked settings keep their value in `state.toml`; `Context.effective()` applies the default, so generators never need to check the other setting themselves.

5. **Tests and docs (`tests/test_fontlab.py`, `README.md`)**:
   - Add unit tests for install/remove atomicity, `fonts.plan()`/`install()` caching, generated fontconfig XML (`render_conf` / `web_conf`), `Context.effective()` fallback when uninstalled, and `preview.compare_setup()`.
   - Update the tables and credits in `README.md` (plus `docs/internals/architecture.md` if paths or `apply()` stages changed).

## Verification

```bash
python3 -m unittest discover -s tests -v
```

When a change affects rendered glyphs or aliases in Chromium:

- Check that `fc-match "<Family>"` and `fc-match "<Family>:weight=500"` resolve to `~/.local/share/fonts/fontlab/...`.
- Run `.agents/skills/render-benchmark/SKILL.md` to verify Chromium pixels in isolation before committing.
