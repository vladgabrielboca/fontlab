"""A Chromium window with a test page, restarted after every apply.

It uses its own profile (~/.cache/fontlab/preview/profile), so it never touches the
main browser session. It starts through the /usr/local/bin wrapper like any other
Chromium launch, so it gets the shim and the private font config.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from html import escape

from . import paths
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


def page(state: State) -> str:
    settings = "   ".join(f"{s.key}={state[s.key]}" for s in SETTINGS)
    rows = "".join(f'<p class="{cls}" title="{label}">{escape(SAMPLE)}</p>' for cls, label in ROWS)
    rows += f'<p class="glyphs">{escape(GLYPHS)}</p>'
    panels = "".join(f'<section class="{cls}"><h2>{label}</h2>{rows}</section>'
                     for cls, label in BACKGROUNDS)
    template = (paths.DATA_DIR / "preview.html").read_text()
    return template.replace("{{SETTINGS}}", escape(settings)).replace("{{PANELS}}", panels)


class Preview:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def show(self, state: State) -> str | None:
        """(Re)start the window with the current state. Returns an error message or None."""
        browser = shutil.which("chromium")
        if not browser:
            return "chromium not found in PATH"
        d = paths.P.preview_dir
        d.mkdir(parents=True, exist_ok=True)
        html = d / "preview.html"
        html.write_text(page(state))
        self.stop()
        self._proc = subprocess.Popen(
            [browser, f"--user-data-dir={d / 'profile'}", "--no-first-run",
             "--no-default-browser-check", "--class=fontlab-preview", f"--app=file://{html}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        return None

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
