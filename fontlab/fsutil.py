"""Small file helpers shared by the apply steps."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def write_if_changed(path: Path, text: str) -> bool:
    """Write text atomically. Returns True when the file content changed."""
    if path.exists() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return True


def remove(path: Path) -> bool:
    """Delete a file if present. Returns True when something was removed."""
    if path.exists() or path.is_symlink():
        path.unlink()
        return True
    return False


def link_or_copy(src: Path, dst: Path) -> None:
    """Hard link when possible (same filesystem, instant), else copy."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def replace_dir(stage: Path, target: Path) -> None:
    """Swap a fully prepared stage directory into place, then drop the old one."""
    old = target.with_name(f".{target.name}.old")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    stage.rename(target)
    shutil.rmtree(old, ignore_errors=True)
