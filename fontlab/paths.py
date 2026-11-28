"""Every file and directory fontlab reads or writes, in one place.

fontlab owns everything listed under "outputs" (in ~/.config/uwsm/env and Vencord's
quickCss.css, only its own marked block). Outside these it changes only the gsettings
font keys, and with sudo the FREETYPE_PROPERTIES and QT_NO_SYNTHESIZED_BOLD lines in
/etc/environment. install.sh adds the /usr/local/bin wrappers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"


@dataclass(frozen=True)
class Paths:
    home: Path

    # --- inputs -------------------------------------------------------------
    @property
    def sources(self) -> Path:
        """Unmodified font files: <family>/400 is the full family, <family>/<weight>
        holds only the faces that differ at that weight (Regular and Italic)."""
        return self.home / ".local/share/fontlab/sources"

    @property
    def windows_fonts(self) -> Path:
        """Windows fonts package. Not under a scanned font folder: Chromium only."""
        return self.sources / "windows/fonts"

    # --- state --------------------------------------------------------------
    @property
    def config_dir(self) -> Path:
        return self.home / ".config/fontlab"

    @property
    def state_file(self) -> Path:
        return self.config_dir / "state.toml"

    @property
    def presets_dir(self) -> Path:
        return self.config_dir / "presets"

    # --- outputs ------------------------------------------------------------
    @property
    def installed_fonts(self) -> Path:
        return self.home / ".local/share/fonts/fontlab"

    @property
    def fontconfig_dir(self) -> Path:
        return self.home / ".config/fontconfig/conf.d"

    @property
    def render_conf(self) -> Path:
        return self.fontconfig_dir / "70-fontlab-render.conf"

    @property
    def web_conf(self) -> Path:
        return self.fontconfig_dir / "71-fontlab-web.conf"

    @property
    def chromium_text_conf(self) -> Path:
        """Read by chromium-env.sh (wrapper flags) and the LD_PRELOAD shim (chromium/text-shim.c)."""
        return self.config_dir / "chromium-text.conf"

    @property
    def chromium_fonts_conf(self) -> Path:
        """Private fontconfig for Chromium-family apps (see chromium.fonts_conf).
        The shim sets FONTCONFIG_FILE to it inside Chromium processes when it exists."""
        return self.config_dir / "chromium-fonts.conf"

    @property
    def session_env_conf(self) -> Path:
        """uwsm's env file, sourced at every login before the compositor starts. fontlab owns
        one marked block in it that adds the shim to LD_PRELOAD (see chromium.py)."""
        return self.home / ".config/uwsm/env"

    @property
    def old_session_env_conf(self) -> Path:
        """Earlier location of the session LD_PRELOAD (environment.d); removed on apply.
        systemd reads it only when the user manager starts, which a logout does not do."""
        return self.home / ".config/environment.d/90-fontlab.conf"

    @property
    def runtime_dir(self) -> Path:
        """Shim library and chromium-env.sh, installed by install.sh."""
        return self.home / ".local/share/fontlab/runtime"

    @property
    def launcher(self) -> Path:
        """Prefix fontlab puts in front of Chromium/Electron apps' desktop Exec lines."""
        return self.runtime_dir / "fontlab-launch"

    @property
    def applications_dir(self) -> Path:
        """User desktop entries. A file here hides the system entry with the same name."""
        return self.home / ".local/share/applications"

    @property
    def desktop_backup(self) -> Path:
        """Originals of the user's own desktop entries that fontlab edited in place."""
        return self.home / ".local/share/fontlab/desktop-backup"

    @property
    def apps_file(self) -> Path:
        """Apps the user added or skipped by hand: {"add": [...], "skip": [...]}."""
        return self.config_dir / "apps.json"

    # --- cache --------------------------------------------------------------
    @property
    def cache_dir(self) -> Path:
        return self.home / ".cache/fontlab"

    @property
    def builds_dir(self) -> Path:
        return self.cache_dir / "builds"

    @property
    def preview_dir(self) -> Path:
        return self.cache_dir / "preview"


ENVIRONMENT_FILE = Path("/etc/environment")
SYSTEM_FONTCONFIG_DIR = Path("/etc/fonts/conf.d")

P = Paths(Path(os.environ.get("HOME", str(Path.home()))))


def configure(home: Path) -> None:
    """Point fontlab at another home directory (tests)."""
    global P
    P = Paths(home)
