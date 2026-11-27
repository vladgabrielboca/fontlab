"""Chromium windows with a test page.

The live window shows the applied settings and is restarted after every apply. It starts
through the /usr/local/bin wrapper like any other Chromium launch, so it gets the shim and
the private font config.

The comparison window shows a saved preset without applying it. It starts the real
/usr/bin/chromium with its own fontconfig file: the preset's render rules and font
files, the user's other fontconfig files, fontlab's installed fonts hidden. When the
preset changes contrast or gamma, the shim reads the preset's values instead.
FreeType darkening and gsettings are left out: neither changes web page text.

Each window has its own profile under ~/.cache/fontlab/preview, so it never touches the
main browser session and the two windows are separate Chromium processes.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from html import escape
from pathlib import Path

from . import chromium, fontconfig, fonts, paths
from .availability import Context
from .fsutil import write_if_changed
from .settings import SETTINGS
from .state import State

SAMPLE = ("The quick brown fox jumps over the lazy dog. Sphinx of black quartz, judge my vow. "
          "il1I| 0Oo rn m cl d 1234567890")
GLYPHS = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ &@#%*(){}[]"
ROWS = [("s11", "sans-serif 11px"), ("s12", "sans-serif 12px"), ("s13", "sans-serif 13px"),
        ("s14", "sans-serif 14px"), ("s16", "sans-serif 16px"), ("s20", "sans-serif 20px"),
        ("s14 ui", "system-ui 14px"), ("s14 arial", "Arial 14px"),
        ("s14 serif", "serif 14px"), ("s13 mono", "monospace 13px")]
BACKGROUNDS = [("black", "black #000"), ("dark", "dark grey #24272e"),
               ("white", "white #fff"), ("grey", "light grey #f0f0f0")]


def page(state: State, label: str = "current settings") -> str:
    settings = "   ".join(f"{s.key}={state[s.key]}" for s in SETTINGS)
    rows = "".join(f'<p class="{cls}" title="{label}">{escape(SAMPLE)}</p>' for cls, label in ROWS)
    rows += f'<p class="glyphs">{escape(GLYPHS)}</p>'
    panels = "".join(f'<section class="{cls}"><h2>{label}</h2>{rows}</section>'
                     for cls, label in BACKGROUNDS)
    template = (paths.DATA_DIR / "preview.html").read_text()
    return (template.replace("{{LABEL}}", escape(label)).replace("{{SETTINGS}}", escape(settings))
            .replace("{{PANELS}}", panels))


def real_chromium() -> str | None:
    """/usr/bin/chromium, skipping fontlab's wrapper, which would add the live settings."""
    return "/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else shutil.which("chromium")


def compare_setup(state: State) -> tuple[dict[str, str], list[str]]:
    """Files for showing `state` without applying it: (environment, extra Chromium flags).
    Builds darkened fonts if the cache does not have them, so it can take a while."""
    ctx = Context.detect()
    state, _ = ctx.effective(state)
    d = paths.P.preview_dir / "compare"
    font_dir = d / "fonts"
    shutil.rmtree(font_dir, ignore_errors=True)
    font_dir.mkdir(parents=True)

    sets = [fs for fs in fonts.plan(state) if fs.sources]
    for family, files in fonts.realize(sets).items():
        (font_dir / family).mkdir()
        for f in files:
            (font_dir / family / f.name).symlink_to(f)

    # The user's own fontconfig files stay; fontlab's two are swapped for the preset's.
    p = paths.P
    ours = {p.render_conf.name: d / "render.conf"}
    write_if_changed(ours[p.render_conf.name],
                     fontconfig.render_conf(state, [g for fs in sets for g in fs.rejects],
                                           google_sans=fonts.installed(sets, "googlesans")))
    windows = state["web_fonts"] == "windows"
    web = None if windows else fontconfig.web_conf(state, inter_available=ctx.has("inter"),
                                                   roboto=fonts.installed(sets, "roboto"))
    if web:
        write_if_changed(d / "web.conf", web)
        ours[p.web_conf.name] = d / "web.conf"
    own = {f.name: f for f in sorted(p.fontconfig_dir.glob("*.conf"))
           if f.name not in (p.render_conf.name, p.web_conf.name)}
    user = [path for _, path in sorted({**own, **ours}.items())]
    user.append(p.fontconfig_dir.parent / "fonts.conf")
    conf = d / "fonts.conf"
    write_if_changed(conf, chromium.private_fonts_conf(
        user, windows=windows, extra_dirs=(font_dir,), hidden_dirs=(p.installed_fonts,),
        purpose="the fontlab preset comparison window",
        rules=chromium.hint_rule(state) + chromium.system_ui_rule(state)))
    env = dict(os.environ, FONTCONFIG_FILE=str(conf))
    subprocess.run(["fc-cache", str(font_dir)], env=env, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for key in ("LD_PRELOAD", "FONTLAB_TEXT_CONF"):
        env.pop(key, None)
    args: list[str] = []
    text = chromium.text_conf(state) if ctx.shim else None
    if text:
        (d / "chromium-text.conf").write_text(text)
        env["FONTLAB_TEXT_CONF"] = str(d / "chromium-text.conf")
        env["LD_PRELOAD"] = str(paths.P.runtime_dir / "fontlab-text-shim.so")
        args = [f"--text-contrast={state['contrast']}", f"--text-gamma={state['gamma']}"]
    return env, args


class Preview:
    def __init__(self, name: str = "preview") -> None:
        self.name = name                  # profile folder, page file and window class
        self._proc: subprocess.Popen | None = None

    @property
    def profile(self) -> Path:
        d = paths.P.preview_dir
        return d / "profile" if self.name == "preview" else d / f"{self.name}-profile"

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def show(self, state: State, label: str = "current settings", browser: str | None = None,
             env: dict[str, str] | None = None, args: list[str] | None = None) -> str | None:
        """(Re)start the window. Returns an error message or None."""
        browser = browser or shutil.which("chromium")
        if not browser:
            return "chromium not found in PATH"
        d = paths.P.preview_dir
        d.mkdir(parents=True, exist_ok=True)
        html = d / f"{self.name}.html"
        html.write_text(page(state, label))
        self.stop()
        self._proc = subprocess.Popen(
            [browser, *(args or []), f"--user-data-dir={self.profile}", "--no-first-run",
             "--no-default-browser-check", f"--class=fontlab-{self.name}", f"--app=file://{html}"],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        return None

    def compare(self, state: State, label: str) -> str | None:
        """Show a state that is not applied (a saved preset). Returns an error or None."""
        env, args = compare_setup(state)
        return self.show(state, label, browser=real_chromium(), env=env, args=args)

    def stop(self) -> None:
        if not self.running:
            self._proc = None
            return
        assert self._proc is not None
        try:
            os.killpg(self._proc.pid, signal.SIGTERM)
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(self._proc.pid, signal.SIGKILL)
            self._proc.wait()
        except ProcessLookupError:
            pass
        self._proc = None
