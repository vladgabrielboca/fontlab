"""Find Chromium and Electron apps and start them through fontlab-launch.

Text contrast and gamma only reach a Chromium-based app when fontlab's shim is
preloaded into it. Two routes cover the ways apps get started:

- From a terminal: the /usr/local/bin wrappers (chromium.APPS, installed by install.sh).
- From the app launcher: the app's desktop entry, unless its Exec already reaches a
  /usr/local/bin wrapper through PATH. fontlab writes a copy into
  ~/.local/share/applications with every Exec line prefixed by fontlab-launch. A copy
  there hides the system entry with the same name. Entries that already live in
  ~/.local/share/applications are edited in place and the original is kept in
  ~/.local/share/fontlab/desktop-backup.

An entry counts as Chromium-based when, first match wins:
- the program's folder holds Chromium's files (icudtl.dat plus resources.pak or
  v8_context_snapshot.bin)
- it is a script that execs such a program, or /usr/lib/<name> or /opt/<name> holds them
- it is an AppImage that holds them (looked at once with --appimage-mount)
- its package ships them or depends on electron (pacman, dpkg or rpm)
- its name is in KNOWN (apps whose real binary is downloaded at run time)
- the user added it with `fontlab apps add`
Results are cached by program path, size and mtime, so later applies are fast.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .fsutil import remove, write_if_changed

MARK = "X-Fontlab-Wrapped=true"
SOURCE_KEY = "X-Fontlab-Source="
WRAPPER_MARK = "fontlab launch wrapper"
KNOWN = {"discord", "discord-ptb", "discord-canary"}   # /usr/bin/discord runs ~/.config/discord/...
SKIP_PROGRAMS = {"flatpak", "snap"}                     # sandboxed: the shim cannot get in
EXEC_RE = re.compile(r"""\bexec\s+(?:-\S+\s+)*(["']?)([^\s"'$`;|&]+)\1""")


@dataclass
class Entry:
    id: str            # desktop file id, e.g. "discord.desktop"
    path: Path         # where the original lives
    text: str          # original content, without fontlab's changes
    user: bool         # lives in ~/.local/share/applications

    def value(self, key: str) -> str | None:
        section = None
        for line in self.text.splitlines():
            if line.startswith("["):
                section = line.strip()
            elif section == "[Desktop Entry]" and line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
        return None

    @property
    def name(self) -> str:
        return self.value("Name") or self.id.removesuffix(".desktop")

    @property
    def program(self) -> str | None:
        return program_of(self.value("Exec") or "")


@dataclass
class App:
    entry: Entry
    reason: str | None     # why it counts as Chromium-based, None when it does not
    skipped: bool = False

    @property
    def wrapped(self) -> bool:
        return bool(self.reason) and not self.skipped

    @property
    def via_wrapper(self) -> bool:
        """Exec names a program that PATH finds as fontlab's /usr/local/bin wrapper, which
        adds the settings by itself. Its entry is left alone: tools that read the Exec
        line (omarchy-launch-browser takes its first word as the browser) must still see
        the browser there, not fontlab-launch."""
        prog = self.entry.program
        return bool(prog) and "/" not in prog and is_fontlab_wrapper(Path(shutil.which(prog) or "/"))


# --- desktop entries --------------------------------------------------------------
def system_dirs() -> list[Path]:
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(d) / "applications" for d in dirs.split(":") if d]


def is_ours(text: str) -> bool:
    return MARK in text.splitlines()


def unwrap(text: str) -> str:
    """Undo wrap(): drop fontlab's keys and the launcher prefix from Exec lines."""
    prefix = f"Exec={quote(str(paths.P.launcher))} "
    out = []
    for line in text.splitlines():
        if line == MARK or line.startswith(SOURCE_KEY):
            continue
        out.append("Exec=" + line[len(prefix):] if line.startswith(prefix) else line)
    return "\n".join(out) + "\n"


def entries() -> list[Entry]:
    """Every desktop entry the launcher would show, with fontlab's changes undone."""
    found: dict[str, Entry] = {}
    user_dir = paths.P.applications_dir
    for base, user in [(user_dir, True)] + [(d, False) for d in system_dirs()]:
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.desktop")):
            did = str(f.relative_to(base)).replace("/", "-")
            if did in found:
                continue
            try:
                text = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if user and is_ours(text):
                if any(line.startswith(SOURCE_KEY) for line in text.splitlines()):
                    continue                    # our copy of a system entry: use the original
                backup = paths.P.desktop_backup / did
                text = backup.read_text() if backup.exists() else unwrap(text)
            found[did] = Entry(did, f, text, user)
    return [e for e in found.values()
            if e.value("Type") == "Application" and e.value("Terminal") != "true" and e.value("Exec")]


def program_of(exec_value: str) -> str | None:
    try:
        words = shlex.split(exec_value)
    except ValueError:
        return None
    while words and (words[0] == "env" or "=" in words[0] or words[0].startswith("-")):
        words.pop(0)
    if not words or Path(words[0]).name in SKIP_PROGRAMS:
        return None
    return words[0]


def quote(path: str) -> str:
    if re.search(r'[\s"\'\\$`]', path):
        return '"' + re.sub(r'(["`$\\])', r"\\\1", path) + '"'
    return path


def wrap(text: str, source: Path | None) -> str:
    """Prefix every Exec line with fontlab-launch. DBusActivatable is dropped so the
    launcher runs Exec instead of asking D-Bus to start the app."""
    launcher = quote(str(paths.P.launcher))
    out = []
    for line in text.splitlines():
        if line.startswith("DBusActivatable="):
            continue
        if line.startswith("Exec="):
            line = f"Exec={launcher} {line[5:]}"
        out.append(line)
        if line.strip() == "[Desktop Entry]":
            out.append(MARK)
            if source:
                out.append(SOURCE_KEY + str(source))
    return "\n".join(out) + "\n"


# --- detection --------------------------------------------------------------------
def chromium_dir(d: Path) -> bool:
    return (d / "icudtl.dat").is_file() and \
        ((d / "resources.pak").is_file() or (d / "v8_context_snapshot.bin").is_file())


def is_fontlab_wrapper(p: Path) -> bool:
    try:
        return p.parent == Path("/usr/local/bin") and WRAPPER_MARK in p.read_text(errors="replace")
    except OSError:
        return False


def resolve(program: str) -> Path | None:
    found = program if "/" in program else shutil.which(program)
    if not found:
        return None
    p = Path(found)
    if is_fontlab_wrapper(p):
        p = Path("/usr/bin") / p.name
    try:
        return p.resolve(strict=True)
    except OSError:
        return None


def head(p: Path, n: int) -> bytes:
    try:
        with p.open("rb") as f:
            return f.read(n)
    except OSError:
        return b""


def is_appimage(p: Path) -> bool:
    h = head(p, 11)
    return h[:4] == b"\x7fELF" and h[8:11] in (b"AI\x01", b"AI\x02")


class Detector:
    """Chromium detection with a cache in ~/.cache/fontlab/apps.json."""

    def __init__(self) -> None:
        self.file = paths.P.cache_dir / "apps.json"
        try:
            self.cache: dict[str, str | None] = json.loads(self.file.read_text())
        except (OSError, ValueError):
            self.cache = {}
        self.dirty = False

    def save(self) -> None:
        if self.dirty:
            write_if_changed(self.file, json.dumps(self.cache, indent=1, sort_keys=True))

    def reason(self, program: str) -> str | None:
        if Path(program).name in KNOWN:
            return "known Chromium-based app"
        p = resolve(program)
        if p is None:
            return None
        st = p.stat()
        key = f"{p}:{st.st_size}:{int(st.st_mtime)}"
        if key not in self.cache:
            self.cache[key] = self.check(p)
            self.dirty = True
        return self.cache[key]

    def check(self, p: Path, depth: int = 0) -> str | None:
        if chromium_dir(p.parent):
            return f"Chromium files in {p.parent}"
        if is_appimage(p):
            return self.check_appimage(p)
        if head(p, 2) == b"#!" and depth < 3 and p.stat().st_size < 256_000:
            for target in EXEC_RE.findall(p.read_text(errors="replace")):
                r = resolve(target[1])
                if r and r != p and (why := self.check(r, depth + 1)):
                    return why
        for d in (Path("/usr/lib"), Path("/usr/lib64"), Path("/opt")):
            for name in (p.name, p.name + "-bin"):
                if chromium_dir(d / name):
                    return f"Chromium files in {d / name}"
        return package_reason(p)

    @staticmethod
    def check_appimage(p: Path) -> str | None:
        """Mount the AppImage read-only (this runs only its runtime, not the app) and look."""
        try:
            proc = subprocess.Popen([str(p), "--appimage-mount"], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return None
        try:
            mount = Path((proc.stdout.readline() if proc.stdout else "").strip())
            if mount.is_dir():
                for d in [mount, *mount.glob("*/"), *mount.glob("usr/lib/*/")]:
                    if chromium_dir(d):
                        return "Electron AppImage"
            return None
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def run(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 else ""


def package_reason(p: Path) -> str | None:
    """The package that owns p ships Chromium's files or depends on electron."""
    if pkg := run(["pacman", "-Qqo", str(p)]).strip():
        files = run(["pacman", "-Qlq", pkg]).splitlines()
        info = run(["pacman", "-Qi", pkg])
        depends = next((line.split(":", 1)[1] for line in info.splitlines()
                        if line.startswith("Depends On")), "")
        if any(w.startswith("electron") for w in depends.split()):
            return f"package {pkg} uses electron"
    elif pkg := run(["dpkg", "-S", str(p)]).split(":", 1)[0].strip():
        files = run(["dpkg", "-L", pkg]).splitlines()
    elif pkg := run(["rpm", "-qf", "--qf", "%{NAME}", str(p)]).strip():
        files = run(["rpm", "-ql", pkg]).splitlines()
    else:
        return None
    listed = set(files)                 # icudtl.dat alone is ICU data (Flutter ships it too)
    for f in listed:
        if f.endswith("/icudtl.dat"):
            d = f[: -len("icudtl.dat")]
            if d + "resources.pak" in listed or d + "v8_context_snapshot.bin" in listed:
                return f"package {pkg} ships Chromium"
    return None


# --- user list ----------------------------------------------------------------------
def load_choices() -> dict[str, list[str]]:
    try:
        data = json.loads(paths.P.apps_file.read_text())
        return {"add": list(data.get("add", [])), "skip": list(data.get("skip", []))}
    except (OSError, ValueError):
        return {"add": [], "skip": []}


def save_choices(choices: dict[str, list[str]]) -> None:
    write_if_changed(paths.P.apps_file, json.dumps(choices, indent=1) + "\n")


def matches(entry: Entry, names: list[str]) -> bool:
    keys = {entry.id, entry.id.removesuffix(".desktop"), entry.name.lower()}
    if entry.program:
        keys.add(Path(entry.program).name)
    return any(n in keys or n.lower() in keys for n in names)


def scan() -> list[App]:
    choices, detector = load_choices(), Detector()
    apps = []
    for e in entries():
        if matches(e, choices["add"]):
            reason = "added with fontlab apps add"
        else:
            reason = detector.reason(e.program) if e.program else None
        apps.append(App(e, reason, skipped=matches(e, choices["skip"])))
    detector.save()
    return apps


# --- apply --------------------------------------------------------------------------
def apply(enabled: bool) -> bool:
    """Wrap every Chromium-based app's desktop entry (enabled), or undo all of it.
    Returns True when a desktop file changed."""
    p = paths.P
    desired: dict[Path, str] = {}
    backups: dict[str, str] = {}
    if enabled and p.launcher.exists():
        for app in scan():
            if not app.wrapped or app.via_wrapper:
                continue
            e = app.entry
            if e.user:
                desired[e.path] = wrap(e.text, None)
                backups[e.id] = e.text
            else:
                desired[p.applications_dir / e.id] = wrap(e.text, e.path)

    changed = False
    if p.applications_dir.is_dir():
        for f in p.applications_dir.rglob("*.desktop"):
            if f in desired:
                continue
            try:
                text = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if not is_ours(text):
                continue
            if any(line.startswith(SOURCE_KEY) for line in text.splitlines()):
                changed |= remove(f)             # our copy of a system entry
            else:                                 # the user's own entry: put the original back
                backup = p.desktop_backup / str(f.relative_to(p.applications_dir)).replace("/", "-")
                changed |= write_if_changed(f, backup.read_text() if backup.exists() else unwrap(text))
                remove(backup)
    for did, text in backups.items():
        write_if_changed(p.desktop_backup / did, text)
    for path, text in desired.items():
        changed |= write_if_changed(path, text)
    if changed and shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(p.applications_dir)],
                       capture_output=True, check=False)
    return changed


def wrapped_count() -> int:
    d = paths.P.applications_dir
    if not d.is_dir():
        return 0
    return sum(1 for f in d.rglob("*.desktop") if is_ours(f.read_text(errors="replace")))
