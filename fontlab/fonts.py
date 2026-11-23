"""Font files: pick sources for the chosen weights, darken them if asked, install them.

Each family is installed into its own directory under ~/.local/share/fonts/fontlab.
A family directory is always replaced as a whole, so two settings can never leave a
mix of files behind. Darkened builds are cached in ~/.cache/fontlab/builds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .fsutil import link_or_copy, replace_dir
from .state import State

# macOS 10.13 darkening at strength 1 (per side, in em).
DARKEN_X_EM = 0.0121
DARKEN_Y_EM = 0.0121 * 1.25
KEEP_BUILDS = 16
MARKER = ".fontlab-key"


class FontError(RuntimeError):
    pass


@dataclass(frozen=True)
class Family:
    name: str
    weight_key: str          # setting that picks the weight
    darkens: bool            # gets the `darkening` setting (TrueType outlines only)
    replaces: tuple[str, ...] = ()   # system font globs hidden while this family is installed
    system_base: bool = False        # weight 400 is the system font: install nothing


FAMILIES: tuple[Family, ...] = (
    Family("inter", "ui_weight", darkens=True),
    Family("adwaita", "ui_weight", darkens=True,
           replaces=("/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
                     "/usr/share/fonts/Adwaita/AdwaitaSans-Italic.ttf")),
    Family("jbm", "mono_weight", darkens=False, system_base=True,
           replaces=("/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
                     "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Italic.ttf")),
    Family("sf", "sf_weight", darkens=False),
)


@dataclass(frozen=True)
class FontSet:
    """What one family directory should contain."""
    family: Family
    key: str                 # identifies the content; written to the marker file
    sources: tuple[Path, ...]
    darken: float

    @property
    def rejects(self) -> tuple[str, ...]:
        return self.family.replaces if self.sources else ()


def source_files(family: Family, weight: str) -> list[Path]:
    root = paths.P.sources / family.name
    base_dir, weight_dir = root / "400", root / weight
    base = [] if family.system_base else sorted(base_dir.glob("*.[ot]tf"))
    if not family.system_base and not base:
        raise FontError(f"no source fonts in {base_dir}. Run scripts/migrate_legacy.py first.")
    if weight == "400":
        return base
    overrides = sorted(weight_dir.glob("*.[ot]tf"))
    if not overrides:
        raise FontError(f"no {family.name} fonts for weight {weight} in {weight_dir}")
    replaced = {f.stem for f in overrides}
    return [f for f in base if f.stem not in replaced] + overrides


def plan(state: State) -> list[FontSet]:
    sets = []
    for family in FAMILIES:
        weight = state[family.weight_key]
        darken = float(state["darkening"]) if family.darkens else 0.0
        key = weight if darken == 0 else f"{weight}-d{state['darkening']}"
        sets.append(FontSet(family, key, tuple(source_files(family, weight)), darken))
    return sets


def _build_dir(fs: FontSet) -> Path:
    return paths.P.builds_dir / f"{fs.family.name}-{fs.key}"


def _darken(jobs: list[tuple[Path, Path, float]]) -> None:
    uv = shutil.which("uv")
    if not uv:
        raise FontError("uv not found in PATH; it runs the darkening builder with fontTools")
    lines = "".join(f"{src}\t{dst}\t{DARKEN_X_EM * k}\t{DARKEN_Y_EM * k}\n" for src, dst, k in jobs)
    builder = paths.PACKAGE_DIR / "fontbuild.py"
    result = subprocess.run([uv, "run", "-q", "--with", "fonttools", "python", "-I", str(builder)],
                            input=lines, text=True, capture_output=True)
    if result.returncode != 0:
        raise FontError(f"darkening build failed:\n{result.stderr.strip()}")


def realize(sets: list[FontSet]) -> dict[str, list[Path]]:
    """The final files for each family. Darkened sets are built once and cached."""
    final: dict[str, list[Path]] = {}
    pending: list[tuple[FontSet, Path]] = []
    for fs in sets:
        if fs.darken == 0:
            final[fs.family.name] = list(fs.sources)
            continue
        out = _build_dir(fs)
        if (out / MARKER).exists():
            os.utime(out)
        else:
            pending.append((fs, out))
        final[fs.family.name] = [out / f.name for f in fs.sources]

    if pending:
        jobs = []
        for fs, out in pending:
            tmp = out.with_name(out.name + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            jobs += [(src, tmp / src.name, fs.darken) for src in fs.sources]
        _darken(jobs)
        for fs, out in pending:
            tmp = out.with_name(out.name + ".tmp")
            (tmp / MARKER).write_text(fs.key + "\n")
            shutil.rmtree(out, ignore_errors=True)
            tmp.rename(out)
        _prune_builds()
    return final


def _prune_builds() -> None:
    builds = sorted((d for d in paths.P.builds_dir.iterdir() if d.is_dir()),
                    key=lambda d: d.stat().st_mtime, reverse=True)
    for old in builds[KEEP_BUILDS:]:
        shutil.rmtree(old, ignore_errors=True)


def installed_key(family: Family) -> str | None:
    marker = paths.P.installed_fonts / family.name / MARKER
    return marker.read_text().strip() if marker.exists() else None


def install(state: State) -> tuple[bool, list[FontSet]]:
    """Make ~/.local/share/fonts/fontlab match the state. Returns (changed, sets)."""
    sets = plan(state)
    todo = [fs for fs in sets if installed_key(fs.family) != (fs.key if fs.sources else None)]
    if not todo:
        return False, sets
    files = realize([fs for fs in todo if fs.sources])
    root = paths.P.installed_fonts
    root.mkdir(parents=True, exist_ok=True)
    for fs in todo:
        target = root / fs.family.name
        if not fs.sources:
            shutil.rmtree(target, ignore_errors=True)
            continue
        stage = root / f".{fs.family.name}.stage"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        for f in files[fs.family.name]:
            link_or_copy(f, stage / f.name)
        (stage / MARKER).write_text(fs.key + "\n")
        replace_dir(stage, target)
    return True, sets


def clean_cache() -> int:
    d = paths.P.builds_dir
    count = sum(1 for _ in d.iterdir()) if d.exists() else 0
    shutil.rmtree(d, ignore_errors=True)
    return count
