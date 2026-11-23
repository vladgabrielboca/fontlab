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


def text_conf(state: State) -> str | None:
    """None when contrast and gamma are Chromium's own values: nothing to add."""
    if state["contrast"] == BY_KEY["contrast"].default and state["gamma"] == BY_KEY["gamma"].default:
        return None
    return f"CONTRAST={state['contrast']}\nGAMMA={state['gamma']}\n"


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


def fonts_conf(state: State) -> str | None:
    """The private fontconfig file, None when Chromium can use the normal one."""
    rule = system_ui_rule(state)
    if state["web_fonts"] == "windows":
        return private_fonts_conf(rules=rule)
    if not rule:
        return None
    return private_fonts_conf([paths.SYSTEM_FONTCONFIG_DIR / "50-user.conf"], windows=False, rules=rule,
                              purpose="Chromium-family apps (CSS system-ui)")


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
    changed |= apps.apply(text is not None or conf is not None)
    return changed
