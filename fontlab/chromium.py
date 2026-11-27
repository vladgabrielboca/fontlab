"""Chromium-family apps: browsers, Electron and CEF apps.

Text contrast/gamma: the wrappers in /usr/local/bin (terminal launches) and fontlab-launch
(desktop entries, see apps.py) source chromium-env.sh, which reads chromium-text.conf.
The file only exists when the values differ from Chromium's own, so at the defaults
every app renders exactly as without fontlab. It passes --text-contrast/--text-gamma on the command line (browser
UI) and preloads the shim, which adds them to renderer launches (web pages); Chromium
does not forward these switches to renderers by itself.

Private fontconfig (chromium_fonts_conf), exported as FONTCONFIG_FILE by chromium-env.sh
whenever web_fonts is not "system":
- CSS system-ui: Chromium takes it from the GTK UI font (gsettings font-name, e.g.
  "Adwaita Sans 11") and never asks fontconfig for "system-ui", so the web font rules miss
  it. The private file maps that family to the web font, for Chromium apps only; GTK apps
  keep their font. Chromium's own tabs and menus use the web font too. The family is read
  when fontlab applies, so a changed GTK font needs another apply.
- windows: the system config minus the user's conf.d, plus the Windows web-font map and
  fontlab's own render settings.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from html import escape
from pathlib import Path

from . import apps, desktop, paths
from .fsutil import remove, write_if_changed
from .settings import BY_KEY
from .state import State

# Launchers that get a wrapper when present in /usr/bin.
APPS = ("chromium", "google-chrome-stable", "brave", "brave-browser", "brave-origin", "vivaldi-stable",
        "microsoft-edge-stable", "spotify", "discord")
WRAPPER_MARK = apps.WRAPPER_MARK
# What CSS system-ui should be for each web_fonts choice ("system": left to the desktop).
SYSTEM_UI = {"inter": "Inter", "sf": "SF Pro Text", "windows": "Segoe UI"}


def lcd_box(state: State) -> bool:
    """Whether the shim swaps Skia's LCD filter: only subpixel text uses it."""
    return state.get("chromium_lcd_filter") == "box" and state["antialias"] in ("rgb", "bgr")


def text_conf(state: State) -> str | None:
    """None when contrast, gamma and the LCD filter are Chromium's own: nothing to add.
    LCD_FILTER=box also keeps the shim in LD_PRELOAD for Chromium's child processes,
    which patch the filter table in their own memory (chromium/text-shim.c)."""
    box = lcd_box(state)
    if (state["contrast"] == BY_KEY["contrast"].default and state["gamma"] == BY_KEY["gamma"].default
            and not box):
        return None
    return f"CONTRAST={state['contrast']}\nGAMMA={state['gamma']}\n" + ("LCD_FILTER=box\n" if box else "")


def needs_launcher(state: State) -> bool:
    """Whether Chromium-based apps must start through fontlab (text flags or private fonts)."""
    return text_conf(state) is not None or fonts_conf(state) is not None


def gtk_ui_family() -> str | None:
    """Family of the GTK UI font: gsettings font-name "Adwaita Sans 11" -> "Adwaita Sans"."""
    if not desktop.gsettings_available():
        return None
    out = subprocess.run(["gsettings", "get", desktop.SCHEMA, "font-name"],
                         capture_output=True, text=True).stdout.strip().strip("'")
    return re.sub(r"\s+[\d.]+$", "", out) or None


def system_ui_rule(state: State) -> str:
    """fontconfig rule sending the GTK UI font to the web font. Empty when there is nothing to do."""
    target = SYSTEM_UI.get(state["web_fonts"])
    ui = gtk_ui_family() if target else None
    if not ui or ui == target:
        return ""
    return (f"  <!-- CSS system-ui: Chromium asks for the GTK UI font, {escape(ui)}. -->\n"
            '  <match target="pattern">\n'
            f'    <test name="family" qual="any"><string>{escape(ui)}</string></test>\n'
            f'    <edit name="family" mode="prepend" binding="strong"><string>{escape(target)}</string></edit>\n'
            "  </match>\n")


def hint_rule(state: State) -> str:
    """fontconfig rule giving Chromium its own grid fitting (chromium_hinting).

    Chromium and FreeType want opposite values: subpixel positioning at `slight` keeps
    ClearType-like spacing, while `full` runs bytecode hints that land glyphs off the
    pixels Windows puts them on. The rule comes after 70-fontlab-render.conf, so it wins
    for Chromium only. Empty when both settings agree."""
    style = state["chromium_hinting"]
    if style == state["hinting"]:
        return ""
    enabled = "false" if style == "none" else "true"
    return ("  <!-- Chromium: grid fitting kept apart from the rest of the desktop. -->\n"
            '  <match target="font">\n'
            f'    <edit name="hinting" mode="assign"><bool>{enabled}</bool></edit>\n'
            f'    <edit name="hintstyle" mode="assign"><const>hint{style}</const></edit>\n'
            "  </match>\n")


def fonts_conf(state: State) -> str | None:
    """The private fontconfig file, None when Chromium can use the normal one."""
    rules = hint_rule(state) + system_ui_rule(state)
    if state["web_fonts"] == "windows":
        return private_fonts_conf(rules=rules)
    if not rules:
        return None
    return private_fonts_conf([paths.SYSTEM_FONTCONFIG_DIR / "50-user.conf"], windows=False, rules=rules,
                              purpose="Chromium-family apps (hinting, system-ui)")


def private_fonts_conf(user_confs: list[Path] | None = None, windows: bool = True,
                       extra_dirs: tuple[Path, ...] = (), hidden_dirs: tuple[Path, ...] = (),
                       purpose: str = "Chromium-family apps (web_fonts = windows)", rules: str = "") -> str:
    """The system config with the user's conf.d swapped for user_confs (default: the
    render conf). windows adds the Windows web-font map and font folder. rules (fontconfig
    XML) go right after user_confs. extra_dirs are scanned too; fonts under hidden_dirs
    are ignored."""
    p = paths.P
    windows_map = paths.DATA_DIR / "web-windows.conf"
    user = [p.render_conf] if user_confs is None else user_confs
    includes: list[Path | str] = []          # str: inline rules
    for f in sorted(paths.SYSTEM_FONTCONFIG_DIR.glob("*.conf")):
        if windows and windows_map not in includes and f.name >= "45":
            includes.append(windows_map)        # before distro rules, like Chrome on Windows
        if f.name == "50-user.conf":
            includes += [*user, rules]
        else:
            includes.append(f)
    if windows and windows_map not in includes:
        includes.append(windows_map)
    if rules not in includes:
        includes.append(rules)
    dirs = ([p.windows_fonts] if windows else []) + list(extra_dirs)
    body = "".join(f if isinstance(f, str) else f'  <include ignore_missing="yes">{escape(str(f))}</include>\n'
                   for f in includes)
    if hidden_dirs:
        body += "  <selectfont><rejectfont>\n"
        body += "".join(f"    <glob>{escape(str(d))}/*</glob>\n" for d in hidden_dirs)
        body += "  </rejectfont></selectfont>\n"
    return ('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
            f"<!-- Generated by fontlab for {escape(purpose)}. -->\n"
            "<fontconfig>\n"
            "  <dir>/usr/share/fonts</dir>\n"
            "  <dir>/usr/local/share/fonts</dir>\n"
            '  <dir prefix="xdg">fonts</dir>\n'
            + "".join(f"  <dir>{escape(str(d))}</dir>\n" for d in dirs) +
            "  <cachedir>/var/cache/fontconfig</cachedir>\n"
            '  <cachedir prefix="xdg">fontconfig</cachedir>\n'
            f"{body}</fontconfig>\n")


def wrapped_apps() -> dict[str, bool]:
    """Chromium-family launchers on this system -> whether fontlab's wrapper is active."""
    out = {}
    for app in APPS:
        if not Path(f"/usr/bin/{app}").exists():
            continue
        wrapper = Path(f"/usr/local/bin/{app}")
        active = (wrapper.exists() and WRAPPER_MARK in wrapper.read_text(errors="replace")
                  and shutil.which(app) == str(wrapper))
        out[app] = active
    return out


SESSION_START = "# fontlab start: session-wide Chromium shim. Turn off with: fontlab set session_shim=off"
SESSION_END = "# fontlab end"
_SESSION_BLOCK = re.compile(r"\n?# fontlab start[^\n]*\n.*?# fontlab end\n?", re.S)


def session_env_text(state: State) -> str | None:
    """fontlab's block for ~/.config/uwsm/env, or None when off. The shim goes first in
    LD_PRELOAD, once: the systemd user manager may already carry it from an earlier login
    or from sync_systemd_session_env."""
    if state.get("session_shim") != "on":
        return None
    shim = paths.P.runtime_dir / "fontlab-text-shim.so"
    return (f"{SESSION_START}\n"
            f'case ":${{LD_PRELOAD-}}:" in\n'
            f"  *:{shim}:*) ;;\n"
            f'  *) export LD_PRELOAD="{shim}${{LD_PRELOAD:+:$LD_PRELOAD}}" ;;\n'
            f"esac\n"
            f"{SESSION_END}\n")


def with_session_block(text: str, block: str | None) -> str:
    """text with fontlab's block replaced by block (None removes it); the rest is kept."""
    rest = _SESSION_BLOCK.sub("\n", text).strip("\n")
    if block is None:
        return rest + "\n" if rest else ""
    return f"{rest}\n\n{block}" if rest else block


def _systemd_ld_preload() -> str | None:
    if not shutil.which("systemctl"):
        return None
    r = subprocess.run(["systemctl", "--user", "show-environment"],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return None
    for ln in r.stdout.splitlines():
        if ln.startswith("LD_PRELOAD="):
            val = ln.split("=", 1)[1]
            # systemctl --user show-environment uses $'...' shell quoting for some values.
            if val.startswith("$'") and val.endswith("'"):
                val = val[2:-1]
            return val
    return ""


def merged_ld_preload(current: str | None, shim: str | None) -> str | None:
    """LD_PRELOAD with fontlab's shim added (shim != None) or removed, keeping other entries."""
    items = [p for p in (current or "").split(":") if p and "fontlab-text-shim.so" not in p]
    if shim:
        items.insert(0, shim)
    return ":".join(items) or None


def sync_systemd_session_env(enabled: bool) -> bool:
    """Update the running systemd --user environment so UWSM/systemd-launched apps pick up
    LD_PRELOAD right away (systemd --user often stays alive across quick logouts).
    Skipped under fake test homes."""
    if paths.P.home != Path.home():
        return False
    cur = _systemd_ld_preload()
    if cur is None:
        return False
    shim = str(paths.P.runtime_dir / "fontlab-text-shim.so") if enabled else None
    want = merged_ld_preload(cur, shim)
    if (cur or None) == want:
        return False
    cmd = ["systemctl", "--user", "set-environment", f"LD_PRELOAD={want}"] if want \
        else ["systemctl", "--user", "unset-environment", "LD_PRELOAD"]
    return subprocess.run(cmd, capture_output=True, check=False).returncode == 0


def _compositor_has_shim() -> bool:
    """Check whether the running graphical compositor (e.g. Hyprland) inherited LD_PRELOAD,
    so fontlab doctor still works accurately even when run inside a Chromium-based terminal
    where the shim already stripped itself from LD_PRELOAD."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return False
    r = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "Hyprland"],
                       capture_output=True, text=True, check=False)
    for pid in r.stdout.split():
        try:
            env = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if any(e.startswith("LD_PRELOAD=") and "fontlab-text-shim.so" in e for e in env.split("\0")):
            return True
    return False


def session_shim_active() -> bool:
    """Whether the session-wide shim is active in the current graphical session."""
    return "fontlab-text-shim.so" in os.environ.get("LD_PRELOAD", "") or _compositor_has_shim()


def apply_session_env(state: State) -> bool:
    """Add or remove fontlab's block in ~/.config/uwsm/env and sync systemd --user.
    Returns True when something changed."""
    p = paths.P.session_env_conf
    block = session_env_text(state)
    old = p.read_text() if p.exists() else ""
    new = with_session_block(old, block)
    if new == old:
        changed = False
    elif new:
        changed = write_if_changed(p, new)
    else:
        changed = remove(p)
    changed |= remove(paths.P.old_session_env_conf)
    changed |= sync_systemd_session_env(block is not None)
    return changed


def session_env_enabled() -> bool:
    """Whether ~/.config/uwsm/env holds fontlab's block."""
    p = paths.P.session_env_conf
    return p.exists() and SESSION_START in p.read_text()


def apply(state: State) -> bool:
    """Returns True when something changed."""
    p = paths.P
    text = text_conf(state)
    changed = write_if_changed(p.chromium_text_conf, text) if text else remove(p.chromium_text_conf)
    conf = fonts_conf(state)
    if conf is None:
        changed |= remove(p.chromium_fonts_conf)
    elif write_if_changed(p.chromium_fonts_conf, conf):
        changed = True
        if state["web_fonts"] == "windows":
            env = dict(os.environ, FONTCONFIG_FILE=str(p.chromium_fonts_conf))
            subprocess.run(["fc-cache", str(p.windows_fonts)], env=env, check=False)
    changed |= apply_session_env(state)
    changed |= apps.apply(text is not None or conf is not None)
    return changed
