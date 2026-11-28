"""Leftovers of the launch routes fontlab used before 2026-11-28, removed on apply.

fontlab used to reach Chromium apps three ways: /usr/local/bin wrappers (install.sh),
desktop entries rewritten to start through fontlab-launch, and the session LD_PRELOAD.
Only the session LD_PRELOAD is left. This module puts the desktop entries back, deletes
the app lists and the session LD_PRELOAD's location before 2026-11-25
(~/.config/environment.d/90-fontlab.conf); install.sh deletes the wrappers (they need sudo). Drop this file once no
machine has the old setup.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import paths
from .fsutil import remove, write_if_changed

MARK = "X-Fontlab-Wrapped=true"
SOURCE_KEY = "X-Fontlab-Source="
WRAPPER_MARK = "fontlab launch wrapper"


def _launcher() -> str:
    path = str(paths.P.runtime_dir / "fontlab-launch")
    if re.search(r'[\s"\'\\$`]', path):
        return '"' + re.sub(r'(["`$\\])', r"\\\1", path) + '"'
    return path


def unwrap(text: str) -> str:
    """A desktop entry without fontlab's keys and launcher prefix."""
    prefix = f"Exec={_launcher()} "
    out = []
    for line in text.splitlines():
        if line == MARK or line.startswith(SOURCE_KEY):
            continue
        out.append("Exec=" + line[len(prefix):] if line.startswith(prefix) else line)
    return "\n".join(out) + "\n"


def cleanup() -> bool:
    """Put wrapped desktop entries back and delete the app lists. True when an entry changed."""
    p = paths.P
    changed = False
    if p.applications_dir.is_dir():
        for f in p.applications_dir.rglob("*.desktop"):
            try:
                text = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            lines = text.splitlines()
            if MARK not in lines:            # a copy made by another tool still calls the launcher
                if f"Exec={_launcher()} " in text:
                    changed |= write_if_changed(f, unwrap(text))
                continue
            if any(line.startswith(SOURCE_KEY) for line in lines):
                changed |= remove(f)                     # fontlab's copy of a system entry
            else:                                        # the user's own entry, edited in place
                backup = p.desktop_backup / str(f.relative_to(p.applications_dir)).replace("/", "-")
                changed |= write_if_changed(f, backup.read_text() if backup.exists() else unwrap(text))
    if changed and shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(p.applications_dir)], capture_output=True, check=False)
    shutil.rmtree(p.desktop_backup, ignore_errors=True)
    remove(p.config_dir / "apps.json")
    remove(p.cache_dir / "apps.json")
    return changed | remove(p.home / ".config/environment.d/90-fontlab.conf")


def wrappers() -> list[Path]:
    """Old launch wrappers still in /usr/local/bin (install.sh removes them)."""
    d = Path("/usr/local/bin")
    found = []
    for f in sorted(d.iterdir()) if d.is_dir() else []:
        try:
            if f.is_file() and WRAPPER_MARK in f.read_text(errors="replace")[:400]:
                found.append(f)
        except OSError:
            pass
    return found
