"""Make the system match a state. Every step only writes when its output differs,
so applying the same state twice does nothing the second time."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

from . import chromium, desktop, fontconfig, fonts, paths, vencord
from .availability import Context
from .fsutil import remove, write_if_changed
from .state import State
from .toolchain import Progress


@dataclass
class Report:
    changed: list[str] = field(default_factory=list)   # what was rewritten
    notices: list[str] = field(default_factory=list)   # what still needs the user

    def summary(self) -> str:
        return "applied: " + ", ".join(self.changed) if self.changed else "already applied"


def fc_cache() -> None:
    subprocess.run(["fc-cache", str(paths.P.installed_fonts.parent)], check=False)


def apply(state: State, *, system: bool = False, progress: Progress = lambda _msg: None) -> Report:
    """system=True also writes /etc/environment, asking for the sudo password."""
    report = Report()
    ctx = Context.detect()
    state, report.notices = ctx.effective(state)

    progress("fonts")
    fonts_changed, sets = fonts.install(state, progress)
    if fonts_changed:
        report.changed.append("fonts")

    progress("fontconfig")
    render, web = fontconfig.confs(state, sets)
    conf_changed = write_if_changed(paths.P.render_conf, render)
    conf_changed |= write_if_changed(paths.P.web_conf, web) if web else remove(paths.P.web_conf)
    if conf_changed:
        report.changed.append("fontconfig")
    if fonts_changed:
        progress("fc-cache")     # caches are per font file; conf rules are read live
        fc_cache()
    if fonts_changed and desktop.shell_restart_available():
        report.notices.append(desktop.SHELL_NOTICE)

    progress("chromium")
    had_session_env = chromium.session_env_enabled()
    if chromium.apply(state, ctx.shim):
        report.changed.append("chromium")
    if chromium.session_env_enabled() != had_session_env:
        report.notices.append("Chromium shim added to or removed from the session: log out and back in so every app gets it")

    progress("vencord")
    if vencord.apply(state):
        report.changed.append("vencord")

    progress("gsettings")
    if desktop.apply_gsettings(state):
        report.changed.append("gsettings")

    if desktop.environment_pending(state):
        if desktop.apply_environment(state, interactive=system):
            report.changed.append("/etc/environment")
            report.notices.append("/etc/environment changed: log out and back in to see it")
        else:
            report.notices.append("/etc/environment needs sudo: press ! in fontlab, "
                                  "or run: fontlab apply --system")
    return report


def uninstall(purge: bool = False) -> list[str]:
    """Remove every output fontlab wrote. purge also removes packages, state and cache.
    /etc/environment is left as it is; uninstall.sh also removes the command and the shim."""
    p = paths.P
    removed = []
    had_session_env = chromium.session_env_enabled()
    chromium.remove_all()
    if had_session_env:
        removed.append(f"fontlab block in {p.session_env_conf}")
    vencord.remove()
    for f in (p.render_conf, p.web_conf):
        if remove(f):
            removed.append(str(f))
    if p.installed_fonts.exists():
        shutil.rmtree(p.installed_fonts)
        removed.append(str(p.installed_fonts))
    desktop.reset_gsettings()
    if purge:
        for d in (p.sources, p.cache_dir, p.config_dir, p.venv):
            if d.exists():
                shutil.rmtree(d)
                removed.append(str(d))
    fc_cache()
    return removed
