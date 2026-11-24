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
from .fsutil import write_if_changed
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
_OLD = re.compile(r"\n?/\* fontlab start[^\n]*\*/.*?/\* fontlab end \*/\n?", re.S)

# Settings folders, relative to $HOME.
CLIENTS = (".config/vesktop/settings", ".config/Vencord/settings", ".config/equibop/settings")


def css_files() -> list[Path]:
    return [paths.P.home / d / "quickCss.css" for d in CLIENTS if (paths.P.home / d).is_dir()]


def with_block(text: str, on: bool) -> str:
    rest = _OLD.sub("\n", text).strip("\n")
    if not on:
        return rest + "\n" if rest else ""
    return f"{rest}\n\n{BLOCK}" if rest else BLOCK


def apply(state: State) -> bool:
    """Add or remove the block. Returns True when a file changed."""
    on = state.get("vencord_fonts") == "on"
    changed = False
    for f in css_files():
        old = f.read_text() if f.exists() else ""
        new = with_block(old, on)
        if new != old and (f.exists() or new):
            changed |= write_if_changed(f, new)
    return changed
