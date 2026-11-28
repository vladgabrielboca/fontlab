"""External programs fontlab relies on, found or set up on demand.

fontTools: the system Python if it has it, else `uv run --with fonttools`, else a private
venv in ~/.local/share/fontlab/venv (created once with pip).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Callable

from . import paths

BUILDER = paths.PACKAGE_DIR / "builders" / "run.py"


class ToolError(RuntimeError):
    pass


def _venv_python() -> str:
    py = paths.P.venv / "bin/python"
    if not py.exists():
        r = subprocess.run([sys.executable, "-m", "venv", str(paths.P.venv)], capture_output=True, text=True)
        if r.returncode != 0:
            raise ToolError("fontTools is missing and a venv could not be created "
                            f"({r.stderr.strip()}). Install python-fonttools or uv.")
    if subprocess.run([str(py), "-c", "import fontTools"], capture_output=True).returncode != 0:
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", "fonttools"], capture_output=True, text=True)
        if r.returncode != 0:
            raise ToolError(f"pip install fonttools failed: {r.stderr.strip()}")
    return str(py)


def fonttools_python() -> list[str]:
    """Command prefix for a Python that can import fontTools."""
    if importlib.util.find_spec("fontTools"):
        return [sys.executable]
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "-q", "--no-project", "--with", "fonttools", "python"]
    return [_venv_python()]


def fonttools_source() -> str:
    """Where fontTools comes from, for `fontlab doctor`."""
    if importlib.util.find_spec("fontTools"):
        return "system Python"
    if shutil.which("uv"):
        return "uv (downloaded on first use)"
    return "private venv (created on first use)"


def run_builder(stdin: str) -> None:
    """Run builders/run.py with JSON build jobs on stdin."""
    result = subprocess.run([*fonttools_python(), str(BUILDER)], input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise ToolError(f"font build failed:\n{result.stderr.strip()[-2000:]}")


Progress = Callable[[str], None]
