"""Chromium-family apps: browsers, Electron and CEF apps.

The text shim (chromium/text-shim.c) is preloaded into the whole login session: a marked
block in ~/.config/uwsm/env adds it to LD_PRELOAD, and the running systemd --user manager
gets the same value. Every process loads it; all but Chromium's leave it after one check.
It is the only way fontlab reaches these apps, however they are started (app launcher,
keybind, terminal, AppImage). Flatpak and Snap apps run sandboxed and are out of reach.

Text contrast/gamma (chromium-text.conf): the shim adds --text-contrast/--text-gamma to a
browser's own command line (browser UI) and to every renderer launch (web pages); Chromium
does not forward these switches to renderers by itself. The file only exists when the
values differ from Chromium's own, so at the defaults every app renders as without fontlab.

Private fontconfig (chromium-fonts.conf), set as FONTCONFIG_FILE by the shim inside the
Chromium process only (children do not inherit it, see text-shim.c child_env), whenever
web_fonts is not "system" or chromium_hinting differs from the desktop's hinting:
- CSS system-ui: Chromium takes it from the GTK UI font (gsettings font-name, e.g.
  "Adwaita Sans 11") and never asks fontconfig for "system-ui", so the web font rules miss
  it. The private file maps that family to the web font, for Chromium apps only; GTK apps
  keep their font. Chromium's own tabs and menus use the web font too. The family is read
  when fontlab applies, so a changed GTK font needs another apply.
- Not windows: the desktop's own /etc/fonts/fonts.conf, then fontlab's rules for Chromium.
  Read live by fontconfig, so a fontconfig or distro update needs no new apply.
- windows: the system config minus the user's conf.d, plus the Windows web-font map and
  fontlab's own render settings. This one lists the system files when fontlab applies.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from html import escape
from pathlib import Path

from . import desktop, fontconfig, legacy, paths
from .fsutil import remove, replace_block, write_if_changed
from .settings import BY_KEY, WEB_FONTS
from .state import State

# Browsers for the preview windows (they can show a test page with --app).
BROWSERS = ("chromium", "google-chrome-stable", "brave", "brave-browser", "brave-origin", "vivaldi-stable",
            "microsoft-edge-stable")


def browser() -> str | None:
    """The first of BROWSERS that is installed, /usr/bin first."""
    for app in BROWSERS:
        if Path(f"/usr/bin/{app}").exists():
            return f"/usr/bin/{app}"
    for app in BROWSERS:
        if found := shutil.which(app):
            return found
    return None


def lcd_box(state: State) -> bool:
    """Whether the shim swaps Skia's LCD filter. With grayscale text the setting is
    locked to stock before it gets here (Setting.active_when)."""
    return state["chromium_lcd_filter"] == "box"


def text_conf(state: State) -> str | None:
    """None when contrast, gamma and the LCD filter are Chromium's own: nothing to add.
    LCD_FILTER=box also keeps the shim in LD_PRELOAD for Chromium's child processes,
    which patch the filter table in their own memory (chromium/text-shim.c)."""
    box = lcd_box(state)
    if (state["contrast"] == BY_KEY["contrast"].default and state["gamma"] == BY_KEY["gamma"].default
            and not box):
        return None
    return f"CONTRAST={state['contrast']}\nGAMMA={state['gamma']}\n" + ("LCD_FILTER=box\n" if box else "")


def gtk_ui_family() -> str | None:
    """Family of the GTK UI font: gsettings font-name "Adwaita Sans 11" -> "Adwaita Sans"."""
    if not desktop.gsettings_available():
        return None
    out = subprocess.run(["gsettings", "get", desktop.SCHEMA, "font-name"],
                         capture_output=True, text=True).stdout.strip().strip("'")
    return re.sub(r"\s+[\d.]+$", "", out) or None


def system_ui_rule(state: State) -> str:
    """fontconfig rule sending the GTK UI font to the web font. Empty when there is nothing to do."""
    target = WEB_FONTS[state["web_fonts"]].system_ui
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
    for Chromium only, monospace included. Empty when hinting and mono_hinting both
    equal chromium_hinting. With darkening on, the icon font rules are repeated after it,
    so icon fonts stay unhinted."""
    style = state["chromium_hinting"]
    if style == state["hinting"] == state["mono_hinting"]:
        return ""
    out = ("  <!-- Chromium: grid fitting kept apart from the rest of the desktop. -->\n"
           '  <match target="font">\n' + fontconfig.hint_edits(style) + "  </match>\n")
    if fontconfig.darkening_on(state):
        out += fontconfig.icon_rules()
    return out


def fonts_conf(state: State) -> str | None:
    """The private fontconfig file, None when Chromium can use the normal one."""
    rules = hint_rule(state) + system_ui_rule(state)
    if state["web_fonts"] == "windows":
        return private_fonts_conf(rules, windows=True)
    if not rules:
        return None
    return _document(f'  <include ignore_missing="yes">{escape(str(paths.SYSTEM_FONTCONFIG_DIR.parent / "fonts.conf"))}</include>\n'
                     + rules)


def _document(body: str) -> str:
    return ('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
            "<!-- Generated by fontlab for Chromium-family apps. Do not edit; run fontlab. -->\n"
            f"<fontconfig>\n{body}</fontconfig>\n")


# Mac-only CSS names. Windows has no font by these names, so Chrome there skips them and
# takes the next family in the list (usually "Segoe UI"). Omarchy's 50-omarchy.conf aliases
# them to Liberation Sans with <prefer>, and Chromium takes any font whose family is the
# first one after substitution, whatever the binding. Putting the name itself first again
# matches no font, so Chromium moves on, as on Windows.
WINDOWS_UNKNOWN = ("-apple-system", "BlinkMacSystemFont")


def windows_late_rules() -> str:
    """Rules that must run after the system confs in Windows mode."""
    return ("  <!-- Mac-only names resolve to nothing, as on Windows. -->\n" + "".join(
        '  <match target="pattern">\n'
        f'    <test name="family" qual="any"><string>{escape(n)}</string></test>\n'
        f'    <edit name="family" mode="prepend_first" binding="strong"><string>{escape(n)}</string></edit>\n'
        "  </match>\n" for n in WINDOWS_UNKNOWN))


def private_fonts_conf(rules: str, *, windows: bool, user_confs: list[Path] | None = None,
                       preview_fonts: Path | None = None) -> str:
    """The system config with the user's conf.d swapped for user_confs (default: the
    render conf). windows adds the Windows web-font map and font folder. rules (fontconfig
    XML) go right after user_confs. preview_fonts: the comparison window's own font
    folder, scanned instead of ~/.local/share/fonts/fontlab."""
    p = paths.P
    windows_map = paths.DATA_DIR / "web-windows.conf"
    user = [p.render_conf] if user_confs is None else user_confs
    if windows:
        rules = windows_late_rules() + rules
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
    dirs = ([p.windows_fonts] if windows else []) + ([preview_fonts] if preview_fonts else [])
    body = "".join(f if isinstance(f, str) else f'  <include ignore_missing="yes">{escape(str(f))}</include>\n'
                   for f in includes)
    if preview_fonts:
        body += f"  <selectfont><rejectfont><glob>{escape(str(p.installed_fonts))}/*</glob></rejectfont></selectfont>\n"
    return _document("  <dir>/usr/share/fonts</dir>\n"
                     "  <dir>/usr/local/share/fonts</dir>\n"
                     '  <dir prefix="xdg">fonts</dir>\n'
                     + "".join(f"  <dir>{escape(str(d))}</dir>\n" for d in dirs) +
                     "  <cachedir>/var/cache/fontconfig</cachedir>\n"
                     '  <cachedir prefix="xdg">fontconfig</cachedir>\n'
                     + body)


SESSION_START = "# fontlab start: Chromium text shim for the whole session. Remove with: fontlab uninstall"
SESSION_END = "# fontlab end"
_SESSION_BLOCK = re.compile(r"\n?# fontlab start[^\n]*\n.*?# fontlab end\n?", re.S)


def session_env_text(on: bool) -> str | None:
    """fontlab's block for ~/.config/uwsm/env, or None when off. The shim goes first in
    LD_PRELOAD, once: the systemd user manager may already carry it from an earlier login
    or from sync_systemd_session_env."""
    if not on:
        return None
    shim = paths.P.shim
    return (f"{SESSION_START}\n"
            f'case ":${{LD_PRELOAD-}}:" in\n'
            f"  *:{shim}:*) ;;\n"
            f'  *) export LD_PRELOAD="{shim}${{LD_PRELOAD:+:$LD_PRELOAD}}" ;;\n'
            f"esac\n"
            f"{SESSION_END}\n")


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
    shim = str(paths.P.shim) if enabled else None
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
    """Whether the shim is preloaded in the current graphical session."""
    return "fontlab-text-shim.so" in os.environ.get("LD_PRELOAD", "") or _compositor_has_shim()


def apply_session_env(on: bool) -> bool:
    """Add or remove fontlab's block in ~/.config/uwsm/env and sync systemd --user.
    Returns True when something changed."""
    p = paths.P.session_env_conf
    block = session_env_text(on)
    old = p.read_text() if p.exists() else ""
    new = replace_block(old, _SESSION_BLOCK, block)
    if new == old:
        changed = False
    elif new:
        changed = write_if_changed(p, new)
    else:
        changed = remove(p)
    changed |= remove(paths.P.old_session_env_conf)    # location used before 2026-11-25
    changed |= sync_systemd_session_env(block is not None)
    return changed


def session_env_enabled() -> bool:
    """Whether ~/.config/uwsm/env holds fontlab's block."""
    p = paths.P.session_env_conf
    return p.exists() and _SESSION_BLOCK.search(p.read_text()) is not None


def remove_all() -> bool:
    """Undo everything: text and font confs, the session block, old launch wrappers."""
    p = paths.P
    changed = remove(p.chromium_text_conf) | remove(p.chromium_fonts_conf)
    return changed | apply_session_env(False) | legacy.cleanup()


def apply(state: State, shim: bool) -> bool:
    """Returns True when something changed. Without the shim nothing could read the
    files, and LD_PRELOAD must not name a missing .so, so everything is undone."""
    if not shim:
        return remove_all()
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
    changed |= apply_session_env(True)
    changed |= legacy.cleanup()
    return changed
