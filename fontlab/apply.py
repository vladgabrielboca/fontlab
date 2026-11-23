"""Make the system match a state. Every step only writes when its output differs,
so applying the same state twice does nothing the second time."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

from . import chromium, desktop, fontconfig, fonts, paths
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
    fonts_changed, sets = fonts.install(state)
    if fonts_changed:
        report.changed.append("fonts")

    progress("fontconfig")
    rejects = [g for fs in sets for g in fs.rejects]
    conf_changed = write_if_changed(paths.P.render_conf, fontconfig.render_conf(state, rejects))
    web = fontconfig.web_conf(state, inter_available=ctx.has("inter"))
    conf_changed |= write_if_changed(paths.P.web_conf, web) if web else remove(paths.P.web_conf)
    if conf_changed:
        report.changed.append("fontconfig")
    if fonts_changed or conf_changed:
        progress("fc-cache")
        fc_cache()

    if ctx.shim:
        progress("chromium")
        if chromium.apply(state):
            report.changed.append("chromium")

    progress("gsettings")
    if desktop.apply_gsettings(state):
        report.changed.append("gsettings")

    if desktop.environment_pending(state):
        if desktop.apply_environment(state, interactive=system):
            report.changed.append("/etc/environment")
            report.notices.append("FreeType darkening changed: log out and back in to see it")
        else:
            report.notices.append("FreeType darkening needs sudo: press ! in fontlab, "
                                  "or run: fontlab apply --system")
    return report


def uninstall(purge: bool = False) -> list[str]:
    """Remove every output fontlab wrote. purge also removes packages, state and cache.
    /etc/environment and the /usr/local/bin wrappers are left to uninstall.sh."""
    p = paths.P
    removed = []
    for f in (p.render_conf, p.web_conf, p.chromium_text_conf, p.chromium_fonts_conf):
        if remove(f):
            removed.append(str(f))
    if p.installed_fonts.exists():
        shutil.rmtree(p.installed_fonts)
        removed.append(str(p.installed_fonts))
    desktop.reset_gsettings()
    if purge:
        for d in (p.sources, p.cache_dir, p.config_dir, p.home / ".local/share/fontlab/venv"):
            if d.exists():
                shutil.rmtree(d)
                removed.append(str(d))
    fc_cache()
    return removed
