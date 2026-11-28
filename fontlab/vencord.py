"""Discord clients with Vencord (Vesktop, Vencord on the official client, Equibop).

Discord ships its own web font (gg sans), which Chromium draws without asking fontconfig,
so none of fontlab's fonts reach it. Vencord's QuickCSS can point Discord's font variables
at the generic families instead, and those go through fontconfig like any web page.
fontlab owns one marked block in each quickCss.css and leaves the rest of the file alone.
Clients that are not installed (no settings folder) are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import paths
from .fsutil import replace_block, write_if_changed
from .state import State

START = "/* fontlab start: Discord uses your fonts. Turn off with: fontlab set vencord_fonts=off */"
END = "/* fontlab end */"
BLOCK = f"""{START}
:root {{
  --font-primary: sans-serif;
  --font-display: sans-serif;
  --font-headline: sans-serif;
  --font-code: monospace;
}}
{END}
"""
_BLOCK_RE = re.compile(r"\n?/\* fontlab start[^\n]*\*/.*?/\* fontlab end \*/\n?", re.S)

# Settings folders, relative to $HOME.
CLIENTS = (".config/vesktop/settings", ".config/Vencord/settings", ".config/equibop/settings")


def css_files() -> list[Path]:
    return [paths.P.home / d / "quickCss.css" for d in CLIENTS if (paths.P.home / d).is_dir()]


def apply(state: State) -> bool:
    """Add or remove the block. Returns True when a file changed."""
    return _write(state["vencord_fonts"] == "on")


def remove() -> bool:
    return _write(False)


def _write(on: bool) -> bool:
    changed = False
    for f in css_files():
        old = f.read_text() if f.exists() else ""
        new = replace_block(old, _BLOCK_RE, BLOCK if on else None)
        if new != old and (f.exists() or new):
            changed |= write_if_changed(f, new)
    return changed
