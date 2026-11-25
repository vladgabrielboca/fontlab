# fontlab Documentation

## For Users

- **[README.md](../README.md)** — Installation, CLI/TUI usage, settings overview, and uninstall instructions.

## Internals

- **[Architecture](internals/architecture.md)** — Module map, `apply()` dataflow, owned paths, Chromium `LD_PRELOAD` shim, desktop entry wrapping, and font package builds.
- **[Rendering Pipeline](internals/rendering-pipeline.md)** — Primary-source technical reference on Chromium/Fontations/Skrifa, Skia `SkMaskGamma`, FreeType stem darkening, and Linux fontconfig behavior.

## Research & Experiments

- **[Experiments Log](research/experiments.md)** — Verified pixel-level benchmarks (Chromium Fontations vs. Firefox FreeType), ruled-out dead ends, top configurations, and Google Sans title-flip investigation.

## Agent Skills

- **[render-benchmark](../.agents/skills/render-benchmark/SKILL.md)** — Run isolated headless Chromium & Firefox pixel-level comparisons safely.
- **[add-font-package](../.agents/skills/add-font-package/SKILL.md)** — End-to-end checklist for adding or changing a font package or setting.
