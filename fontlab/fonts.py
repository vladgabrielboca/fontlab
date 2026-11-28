"""Installed fonts: build the chosen weight and darkening from package files, and
install them.

Each family is installed into its own folder under ~/.local/share/fonts/fontlab and
replaced as a whole, so two settings can never leave a mix of files behind. Built files
are cached in ~/.cache/fontlab/builds, keyed by every input file's fingerprint, the
weight, the darkening and BUILDER_VERSION: a package reinstall or a system update of a
file a build reads makes the next apply build again. A face instanced at a weight is
cached on its own, before darkening, so changing the darkening at the same weight only
darkens. A family with nothing to install has an empty folder (or none, if it never had
files), and hides no system fonts.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .fsutil import link_or_copy, replace_dir
from .packages import PACKAGES, Package, WeightFace, fingerprint
from .state import State
from .toolchain import Progress, run_builder

# macOS 10.13 darkening at strength 1 (per side, in em).
DARKEN_X_EM = 0.0121
DARKEN_Y_EM = 0.0121 * 1.25
KEEP_BUILDS = 32
# Bump when builders/ change their output, so cached builds are made again.
# 3: weights are built at apply time, together with darkening.
BUILDER_VERSION = 3
MARKER = ".fontlab-key"


def families() -> list[Package]:
    """Packages whose files fontlab installs as desktop fonts, one folder each."""
    return [p for p in PACKAGES if p.installs]


@dataclass(frozen=True)
class FontSet:
    """What one family folder should contain: `sources` as they are (or darkened), and
    `faces` rebuilt at `weight`. Nothing at all = no folder."""
    family: Package
    key: str                 # identifies the content; written to the marker file
    sources: tuple[Path, ...]
    darken: float
    replaces: tuple[str, ...]
    weight: str = "400"
    faces: tuple[WeightFace, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.sources and not self.faces

    @property
    def rejects(self) -> tuple[str, ...]:
        return () if self.empty else self.replaces

    @property
    def builds(self) -> bool:
        return bool(self.faces) or (self.darken > 0 and bool(self.sources))


def _key(*data) -> str:
    return hashlib.sha1(json.dumps(data).encode()).hexdigest()[:12]


def plan(state: State) -> list[FontSet]:
    sets = []
    for family in families():
        if not family.installed:
            sets.append(FontSet(family, "", (), 0.0, ()))
            continue
        weight = state[family.weight_key] if family.weight_key else "400"
        faces = family.weight_faces() if weight != "400" else []
        if not faces:
            weight = "400"
        darkening = state["darkening"] if family.darkens else "0.00"
        rebuilt = {f.base for f in faces}
        sources = [f for f in family.base_files() if f not in rebuilt]
        inputs = sources + [p for f in faces for p in (f.base, f.variable)]
        key = _key(BUILDER_VERSION, family.id, weight, darkening, sorted((str(f), fingerprint(f)) for f in inputs))
        sets.append(FontSet(family, key, tuple(sources), float(darkening), tuple(family.replaces()), weight,
                            tuple(faces)))
    return sets


def _stage_dir(target: Path) -> Path:
    """Where a build is made before it is swapped into target."""
    return target.with_name(target.name + ".tmp")


def _build_dir(fs: FontSet) -> Path:
    return paths.P.builds_dir / f"{fs.family.id}-{fs.key}"


def _instance_dir(family: Package, f: WeightFace, weight: str) -> Path:
    """Cache folder of one face instanced at a weight, before darkening."""
    return paths.P.builds_dir / (
        f"{family.id}-i-" + _key(BUILDER_VERSION, family.id, f.method, dict(f.axes), weight, str(f.base),
                                 fingerprint(f.base), str(f.variable), fingerprint(f.variable)))


def realize(sets: list[FontSet], progress: Progress = lambda _msg: None) -> dict[str, list[Path]]:
    """The final files for each family. Built files are made once and cached; everything
    missing is built in one parallel builder run."""
    final: dict[str, list[Path]] = {}
    pending: list[tuple[Path, str, list[dict]]] = []     # target folder, its key, its jobs
    building: list[str] = []
    for fs in sets:
        if not fs.builds:
            final[fs.family.id] = list(fs.sources)
            continue
        out, files, jobs = _build_dir(fs), [], []
        dark = [DARKEN_X_EM * fs.darken, DARKEN_Y_EM * fs.darken] if fs.darken > 0 else None
        if dark and (out / MARKER).exists():             # the family, darkened, is cached as a whole
            os.utime(out)
            final[fs.family.id] = [out / f.base.name for f in fs.faces] + [out / f.name for f in fs.sources]
            continue
        before = len(pending)
        tmp = _stage_dir(out)
        if dark:
            pending.append((out, fs.key, jobs))
        for f in fs.faces:
            inst, name = _instance_dir(fs.family, f, fs.weight), f.base.name
            files.append(out / name if dark else inst / name)
            if (inst / MARKER).exists():                 # instanced at this weight before: only darken
                os.utime(inst)
                if dark:
                    jobs.append({"src": str(inst / name), "darken": dark, "out": str(tmp / name)})
                continue
            instanced = str(_stage_dir(inst) / name)
            job = {"src": str(f.base), "variable": str(f.variable), "method": f.method, "axes": dict(f.axes),
                   "wght": float(fs.weight), "out": instanced}
            if dark:
                job |= {"out": str(tmp / name), "darken": dark, "instance_out": instanced}
                jobs.append(job)
            pending.append((inst, inst.name, [] if dark else [job]))
        if dark:
            jobs += [{"src": str(f), "darken": dark, "out": str(tmp / f.name)} for f in fs.sources]
            files += [out / f.name for f in fs.sources]
        else:
            files += list(fs.sources)
        final[fs.family.id] = files
        if len(pending) > before:
            building.append(fs.family.name)

    if pending:
        progress("building " + ", ".join(building))
        for target, _, _ in pending:
            tmp = _stage_dir(target)
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
        jobs = [j for _, _, js in pending for j in js]
        run_builder(stdin="".join(json.dumps(j) + "\n" for j in jobs))
        for target, key, _ in pending:
            tmp = _stage_dir(target)
            (tmp / MARKER).write_text(key + "\n")
            shutil.rmtree(target, ignore_errors=True)
            tmp.rename(target)
        _prune_builds()
    return final


def _prune_builds() -> None:
    """Keep the KEEP_BUILDS newest darkened builds and the KEEP_BUILDS newest instanced
    faces (`-i-`), counted apart: each weight makes one instanced folder per face, which
    would otherwise push darkened builds out. Leftover .tmp folders (an interrupted build)
    go first and never count, so they cannot push out a build in use."""
    kinds: dict[bool, list[Path]] = {True: [], False: []}
    for d in paths.P.builds_dir.iterdir():
        if d.is_dir() and d.name.endswith(".tmp"):
            shutil.rmtree(d, ignore_errors=True)
        elif d.is_dir():
            kinds["-i-" in d.name].append(d)
    for builds in kinds.values():
        builds.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        for old in builds[KEEP_BUILDS:]:
            shutil.rmtree(old, ignore_errors=True)


def installed_key(family: Package) -> str | None:
    marker = paths.P.installed_fonts / family.id / MARKER
    return marker.read_text().strip() if marker.exists() else None


def install(state: State, progress: Progress = lambda _msg: None) -> tuple[bool, list[FontSet]]:
    """Make ~/.local/share/fonts/fontlab match the state. Returns (changed, sets)."""
    sets = plan(state)
    todo = [fs for fs in sets if installed_key(fs.family) != (None if fs.empty else fs.key)]
    root = paths.P.installed_fonts
    known = {fs.family.id for fs in sets}
    # Folders of packages fontlab no longer has (roboto, sf... dropped 2026-11-28).
    orphans = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")
               and d.name not in known] if root.is_dir() else []
    if not todo and not orphans:
        return False, sets
    files = realize([fs for fs in todo if not fs.empty], progress)
    root.mkdir(parents=True, exist_ok=True)
    dirs = [root] + [root / fs.family.id for fs in todo]
    before = {d: d.stat().st_mtime_ns for d in dirs if d.exists()}
    for d in orphans:
        shutil.rmtree(d)
    for fs in todo:
        # A family without files keeps an empty folder, so the folder never comes and
        # goes and its old mtime is always known to newer_than() below.
        stage = root / f".{fs.family.id}.stage"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        if not fs.empty:
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
