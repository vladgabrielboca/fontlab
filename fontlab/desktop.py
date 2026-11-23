"""Desktop-wide settings outside fontconfig.

gsettings: GTK and the Chromium UI read antialiasing and hinting from here (GNOME schema;
skipped where it is not installed).
/etc/environment: FREETYPE_PROPERTIES for FreeType apps, QT_NO_SYNTHESIZED_BOLD for Qt. Root-owned and read at
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
    # lucidglyph's line: darkening stays at 0.4 px up to 2500 and fades out by 4000,
    # where FreeType's default (…,1667,275,2333,0) fades out much sooner.
    "strong": "autofitter:no-stem-darkening=0 autofitter:darkening-parameters=500,400,1000,400,2500,400,4000,0 "
              "cff:no-stem-darkening=0 type1:no-stem-darkening=0 t1cid:no-stem-darkening=0",
}


# Qt apps read the font list once at start. After fontlab replaces or removes a font file,
# a long-running one (the Omarchy shell) draws that font's text with the wrong glyphs or a
# fallback (Arabic, on Omarchy) until it restarts.
SHELL_RESTART = "omarchy-restart-shell"
SHELL_NOTICE = "font files changed: press R to restart the Omarchy shell (or: omarchy restart shell)"


def shell_restart_available() -> bool:
    return shutil.which(SHELL_RESTART) is not None


def restart_shell() -> None:
    """Raises RuntimeError with the script's message when the restart fails."""
    r = subprocess.run([SHELL_RESTART], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"{SHELL_RESTART} failed")


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


# Every property any FREETYPE choice sets, so switching choices removes the old ones.
OWN_PROPERTIES = ("cff:no-stem-darkening=", "autofitter:no-stem-darkening=",
                  "autofitter:darkening-parameters=", "type1:no-stem-darkening=", "t1cid:no-stem-darkening=")


def merged_freetype(current: str | None, state: State) -> str | None:
    """FREETYPE_PROPERTIES with fontlab's properties set and every other one kept."""
    tokens = [t for t in (current or "").split() if not t.startswith(OWN_PROPERTIES)]
    tokens += (FREETYPE[state["freetype_darkening"]] or "").split()
    return " ".join(tokens) or None


def _desired(var: str, current: str | None, state: State) -> str | None:
    if var == "FREETYPE_PROPERTIES":
        return current if state["freetype_darkening"] == "keep" else merged_freetype(current, state)
    choice = state["qt_no_synth_bold"]
    return current if choice == "keep" else ("1" if choice == "on" else None)


MANAGED = ("FREETYPE_PROPERTIES", "QT_NO_SYNTHESIZED_BOLD")


def _parse(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        key, eq, value = line.partition("=")
        if eq and key in MANAGED:
            values[key] = value.strip().strip('"\'')
    return values


def current_environment() -> dict[str, str]:
    """fontlab's variables in /etc/environment, without quotes."""
    if not paths.ENVIRONMENT_FILE.exists():
        return {}
    return _parse(paths.ENVIRONMENT_FILE.read_text())


def environment_text(current_text: str, state: State) -> str:
    """/etc/environment with only fontlab's lines updated. Other lines stay as they are."""
    old = _parse(current_text)
    lines = [ln for ln in current_text.splitlines() if ln.partition("=")[0] not in MANAGED]
    for var in MANAGED:
        value = _desired(var, old.get(var), state)
        if value:
            lines.append(f'{var}="{value}"')
    return "\n".join(lines) + "\n" if lines else ""


def environment_pending(state: State) -> bool:
    current = {k: " ".join(v.split()) for k, v in current_environment().items()}
    return any(_desired(var, current.get(var), state) != current.get(var) for var in MANAGED)


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
