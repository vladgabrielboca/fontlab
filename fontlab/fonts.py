"""Installed fonts: pick package files for the chosen weights, darken them if asked,
and install them.

Each family is installed into its own folder under ~/.local/share/fonts/fontlab and
replaced as a whole, so two settings can never leave a mix of files behind. Darkened
builds are cached in ~/.cache/fontlab/builds. A family with nothing to install has an
empty folder (or none, if it never had files), and hides no system fonts.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .fsutil import link_or_copy, replace_dir
from .packages import PACKAGES, Manifest, Package
from .state import State
from .toolchain import run_builder

# macOS 10.13 darkening at strength 1 (per side, in em).
DARKEN_X_EM = 0.0121
DARKEN_Y_EM = 0.0121 * 1.25
KEEP_BUILDS = 16
MARKER = ".fontlab-key"


class FontError(RuntimeError):
    pass


def families() -> list[Package]:
    """Packages whose files fontlab installs as desktop fonts, one folder each."""
    return [p for p in PACKAGES if p.installs]


@dataclass(frozen=True)
class FontSet:
    """What one family folder should contain. No sources = no folder."""
    family: Package
    key: str                 # identifies the content; written to the marker file
    sources: tuple[Path, ...]
    darken: float
    replaces: tuple[str, ...]

    @property
    def rejects(self) -> tuple[str, ...]:
        return self.replaces if self.sources else ()


def source_files(family: Package, manifest: Manifest, weight: str) -> list[Path]:
    root = family.root
    if weight not in manifest.weights:
        weight = "400"
    base = [] if family.system_base else sorted((root / "400").glob("*.[ot]tf"))
    if weight == "400":
        return base
    overrides = sorted((root / weight).glob("*.[ot]tf"))
    if not overrides:
        raise FontError(f"{family.id}: no files for weight {weight} in {root / weight}")
    replaced = {f.stem for f in overrides}
    return [f for f in base if f.stem not in replaced] + overrides


def plan(state: State) -> list[FontSet]:
    sets = []
    for family in families():
        manifest = family.manifest()
        if manifest is None:
            sets.append(FontSet(family, "", (), 0.0, ()))
            continue
        weight = state[family.weight_key] if family.weight_key else "400"
        darken = float(state["darkening"]) if family.darkens else 0.0
        key = weight if darken == 0 else f"{weight}-d{state['darkening']}"
        key += "-" + hashlib.sha1(manifest.version.encode()).hexdigest()[:6]   # rebuild on reinstall
        files = tuple(source_files(family, manifest, weight))
        sets.append(FontSet(family, key, files, darken, tuple(manifest.replaces)))
    return sets


def installed(sets: list[FontSet], package: str) -> bool:
    """Whether the plan installs any files for this package."""
    return any(fs.sources for fs in sets if fs.family.id == package)


def _build_dir(fs: FontSet) -> Path:
    return paths.P.builds_dir / f"{fs.family.id}-{fs.key}"


def realize(sets: list[FontSet]) -> dict[str, list[Path]]:
    """The final files for each family. Darkened sets are built once and cached."""
    final: dict[str, list[Path]] = {}
    pending: list[tuple[FontSet, Path]] = []
    for fs in sets:
        if fs.darken == 0:
            final[fs.family.id] = list(fs.sources)
            continue
        out = _build_dir(fs)
        if (out / MARKER).exists():
            os.utime(out)
        else:
            pending.append((fs, out))
        final[fs.family.id] = [out / f.name for f in fs.sources]

    if pending:
        jobs = ""
        for fs, out in pending:
            tmp = out.with_name(out.name + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            jobs += "".join(f"{src}\t{tmp / src.name}\t{DARKEN_X_EM * fs.darken}\t{DARKEN_Y_EM * fs.darken}\n"
                            for src in fs.sources)
        run_builder(["darken"], stdin=jobs)
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


def installed_key(family: Package) -> str | None:
    marker = paths.P.installed_fonts / family.id / MARKER
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
    dirs = [root] + [root / fs.family.id for fs in todo]
    before = {d: d.stat().st_mtime_ns for d in dirs if d.exists()}
    for fs in todo:
        # A family without files keeps an empty folder, so the folder never comes and
        # goes and its old mtime is always known to newer_than() below.
        stage = root / f".{fs.family.id}.stage"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        if fs.sources:
            for f in files[fs.family.id]:
                link_or_copy(f, stage / f.name)
            (stage / MARKER).write_text(fs.key + "\n")
        replace_dir(stage, root / fs.family.id)
    for d, old in before.items():
        newer_than(d, old)
    return True, sets


def newer_than(d: Path, old_ns: int) -> None:
    """fontconfig trusts a folder's cache while the folder's mtime has the same whole
    second as when the cache was written. Two applies in one second (the TUI does that)
    would leave fc-cache sure the old cache is still right: the new fonts stay invisible
    until something else touches the folder. Move the mtime to the next second then."""
    sec = 1_000_000_000
    if d.stat().st_mtime_ns // sec == old_ns // sec:
        t = (old_ns // sec + 1) * sec
        os.utime(d, ns=(t, t))


def clean_cache() -> int:
    d = paths.P.builds_dir
    count = sum(1 for _ in d.iterdir()) if d.exists() else 0
    shutil.rmtree(d, ignore_errors=True)
    return count
