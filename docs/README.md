# fontlab Documentation

## User guide

- [README.md](../README.md): install, CLI/TUI usage, settings and uninstall.

## Internals

- [Architecture](internals/architecture.md): how `apply()` works, managed paths, font builds and the Chromium `LD_PRELOAD` shim.
- [Rendering Pipeline](internals/rendering-pipeline.md): upstream Chromium/Fontations, Skia `SkMaskGamma`, FreeType stem darkening and Linux fontconfig behavior.

## Research

- [Experiments Log](research/experiments.md): Chromium Fontations vs. Firefox FreeType benchmarks, ruled-out configs and the Google Sans title-flip fix.

## Agent skills

- [render-benchmark](../.agents/skills/render-benchmark/SKILL.md): run isolated headless Chromium and Firefox pixel comparisons.
- [add-font-package](../.agents/skills/add-font-package/SKILL.md): checklist for adding or updating a font package or setting.
