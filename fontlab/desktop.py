"""Desktop-wide settings outside fontconfig.

gsettings: GTK and the Chromium UI read antialiasing and hinting from here.
/etc/environment: FREETYPE_PROPERTIES for FreeType apps. Root-owned and read at
login, so changing it needs sudo and a new login.
"""

from __future__ import annotations

import subprocess
import tempfile

from . import paths
from .state import State

SCHEMA = "org.gnome.desktop.interface"
FREETYPE = {
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


def apply_gsettings(state: State) -> bool:
    changed = False
    for key, value in gsettings_values(state).items():
        current = subprocess.run(["gsettings", "get", SCHEMA, key],
                                 capture_output=True, text=True).stdout.strip().strip("'")
        if current != value:
            subprocess.run(["gsettings", "set", SCHEMA, key, value], check=True)
            changed = True
    return changed


def environment_text(current: str, state: State) -> str:
    """/etc/environment with only the FREETYPE_PROPERTIES line replaced."""
    lines = [l for l in current.splitlines() if not l.startswith("FREETYPE_PROPERTIES=")]
    value = FREETYPE[state["freetype_darkening"]]
    if value:
        lines.append(f'FREETYPE_PROPERTIES="{value}"')
    return "\n".join(lines) + "\n"


def environment_pending(state: State) -> bool:
    current = paths.ENVIRONMENT_FILE.read_text() if paths.ENVIRONMENT_FILE.exists() else ""
    return environment_text(current, state) != current


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
