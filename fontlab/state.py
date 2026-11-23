"""The desired settings (state.toml) and named presets (presets/<name>.toml).

The state file is the only source of truth. `apply` makes the system match it, so
editing it by hand and running `fontlab apply` is always safe.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from . import paths
from .settings import BY_KEY, DEFAULTS, SETTINGS

State = dict[str, str]

PRESET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StateError(ValueError):
    pass


def validate(key: str, value: str) -> None:
    if key not in BY_KEY:
        raise StateError(f"unknown setting '{key}'. Known: {', '.join(BY_KEY)}")
    choices = BY_KEY[key].choices
    if value not in choices:
        raise StateError(f"{key}: '{value}' is not allowed. Choices: {' '.join(choices)}")


def normalize(key: str, value: str) -> str:
    """Accept 0.5 for 0.50 and 1.4 for 1.40, so typed numbers match the list."""
    choices = BY_KEY[key].choices if key in BY_KEY else ()
    if value in choices:
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    for choice in choices:
        try:
            if abs(float(choice) - number) < 1e-9:
                return choice
        except ValueError:
            pass
    return value


def read(path: Path) -> State:
    """Read a state or preset file. Missing keys get defaults; bad values are errors."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    state = dict(DEFAULTS)
    for key, value in raw.items():
        value = normalize(key, str(value))
        validate(key, value)
        state[key] = value
    return state


def write(path: Path, state: State, header: str) -> None:
    lines = [f"# {header}"]
    group = None
    for s in SETTINGS:
        if s.group != group:
            group = s.group
            lines += ["", f"# {group}"]
        lines.append(f'{s.key} = "{state[s.key]}"')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)


def load() -> State:
    f = paths.P.state_file
    return read(f) if f.exists() else dict(DEFAULTS)


def save(state: State) -> None:
    write(paths.P.state_file, state, "fontlab state. Edit freely, then run: fontlab apply")


def preset_path(name: str) -> Path:
    if not PRESET_NAME.match(name):
        raise StateError(f"bad preset name '{name}' (letters, digits, . _ -)")
    return paths.P.presets_dir / f"{name}.toml"


def save_preset(name: str, state: State) -> None:
    write(preset_path(name), state, f"fontlab preset '{name}'. Load with: fontlab preset load {name}")


def load_preset(name: str) -> State:
    f = preset_path(name)
    if not f.exists():
        raise StateError(f"no preset '{name}'. Saved: {', '.join(list_presets()) or 'none'}")
    return read(f)


def delete_preset(name: str) -> None:
    preset_path(name).unlink(missing_ok=False)


def list_presets() -> list[str]:
    d = paths.P.presets_dir
    return sorted(p.stem for p in d.glob("*.toml")) if d.exists() else []
