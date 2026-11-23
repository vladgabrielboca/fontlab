"""Desktop-wide settings outside fontconfig.

gsettings: GTK and the Chromium UI read antialiasing and hinting from here (GNOME schema;
skipped where it is not installed).
/etc/environment: FREETYPE_PROPERTIES for FreeType apps. Root-owned and read at
login, so changing it needs sudo and a new login.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile

from . import paths
from .state import State

SCHEMA = "org.gnome.desktop.interface"
FREETYPE = {      # "keep" is not here: fontlab then never touches /etc/environment
    "off": None,
    "cff": "cff:no-stem-darkening=0",
    "all": "cff:no-stem-darkening=0 autofitter:no-stem-darkening=0",
}


def gsettings_values(state: State) -> dict[str, str]:
    aa = state["antialias"]
    values = {"font-antialiasing": "grayscale" if aa == "grayscale" else "rgba",
              "font-hinting": state["hinting"]}
    if aa != "grayscale":
        values["font-rgba-order"] = aa
    return values


def gsettings_available() -> bool:
    if not shutil.which("gsettings"):
        return False
    r = subprocess.run(["gsettings", "list-keys", SCHEMA], capture_output=True, text=True)
    return r.returncode == 0 and "font-hinting" in r.stdout


def apply_gsettings(state: State) -> bool:
    """No-op on systems without GNOME's interface schema."""
    if not gsettings_available():
        return False
    changed = False
    for key, value in gsettings_values(state).items():
        current = subprocess.run(["gsettings", "get", SCHEMA, key],
                                 capture_output=True, text=True).stdout.strip().strip("'")
        if current != value:
            subprocess.run(["gsettings", "set", SCHEMA, key, value], check=True)
            changed = True
    return changed


def reset_gsettings() -> None:
    if gsettings_available():
        for key in ("font-antialiasing", "font-rgba-order", "font-hinting"):
            subprocess.run(["gsettings", "reset", SCHEMA, key], check=False)


OWN_PROPERTIES = ("cff:no-stem-darkening=", "autofitter:no-stem-darkening=")


def merged_freetype(current: str | None, state: State) -> str | None:
    """FREETYPE_PROPERTIES with fontlab's two properties set and every other one kept."""
    tokens = [t for t in (current or "").split() if not t.startswith(OWN_PROPERTIES)]
    tokens += (FREETYPE[state["freetype_darkening"]] or "").split()
    return " ".join(tokens) or None


def current_freetype() -> str | None:
    """The FREETYPE_PROPERTIES value in /etc/environment, without quotes."""
    if not paths.ENVIRONMENT_FILE.exists():
        return None
    for line in paths.ENVIRONMENT_FILE.read_text().splitlines():
        if line.startswith("FREETYPE_PROPERTIES="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return None


def environment_text(current_text: str, state: State) -> str:
    """/etc/environment with only the FREETYPE_PROPERTIES line updated."""
    lines, old = [], None
    for line in current_text.splitlines():
        if line.startswith("FREETYPE_PROPERTIES="):
            old = line.split("=", 1)[1].strip().strip('"\'')
        else:
            lines.append(line)
    value = merged_freetype(old, state)
    if value:
        lines.append(f'FREETYPE_PROPERTIES="{value}"')
    return "\n".join(lines) + "\n" if lines else ""


def environment_pending(state: State) -> bool:
    if state["freetype_darkening"] == "keep":
        return False
    current = current_freetype()
    normalized = " ".join(current.split()) if current else None
    return merged_freetype(current, state) != normalized


def apply_environment(state: State, interactive: bool) -> bool:
    """Write /etc/environment through sudo. Without `interactive`, only works when sudo
    needs no password. Returns True when the file now matches."""
    if not environment_pending(state):
        return True
    current = paths.ENVIRONMENT_FILE.read_text() if paths.ENVIRONMENT_FILE.exists() else ""
    with tempfile.NamedTemporaryFile("w", suffix=".environment") as tmp:
        tmp.write(environment_text(current, state))
        tmp.flush()
        cmd = ["sudo"] + ([] if interactive else ["-n"]) + \
              ["install", "-m644", tmp.name, str(paths.ENVIRONMENT_FILE)]
        result = subprocess.run(cmd, capture_output=not interactive)
    return result.returncode == 0
