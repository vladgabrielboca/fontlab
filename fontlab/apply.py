"""Make the system match a state. Every step only writes when its output differs,
so applying the same state twice does nothing the second time."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from . import chromium, desktop, fontconfig, fonts, paths
from .fsutil import write_if_changed
from .state import State


@dataclass
class Report:
    changed: list[str] = field(default_factory=list)   # what was rewritten
    notices: list[str] = field(default_factory=list)   # what still needs the user

    def summary(self) -> str:
        if not self.changed:
            return "already applied"
        return "applied: " + ", ".join(self.changed)


def apply(state: State, *, system: bool = False,
          progress: Callable[[str], None] = lambda _msg: None) -> Report:
    """system=True also writes /etc/environment, asking for the sudo password."""
    report = Report()

    progress("fonts")
    fonts_changed, sets = fonts.install(state)
    if fonts_changed:
        report.changed.append("fonts")

    progress("fontconfig")
    rejects = [g for fs in sets for g in fs.rejects]
    conf_changed = write_if_changed(paths.P.render_conf, fontconfig.render_conf(state, rejects))
    conf_changed |= write_if_changed(paths.P.web_conf, fontconfig.web_conf(state))
    if conf_changed:
        report.changed.append("fontconfig")
    if fonts_changed or conf_changed:
        progress("fc-cache")
        subprocess.run(["fc-cache", str(paths.P.installed_fonts.parent)], check=False)

    progress("chromium")
    chromium_changed, notices = chromium.apply(state)
    report.notices += notices
    if chromium_changed:
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
