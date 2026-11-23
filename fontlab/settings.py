"""The settings fontlab controls. Every value is a string picked from a fixed list,
so the TUI (left/right), the CLI (key=value) and the state file all work the same way.
"""

from __future__ import annotations

from dataclasses import dataclass


def steps(start: float, stop: float, step: float, digits: int) -> tuple[str, ...]:
    count = round((stop - start) / step)
    return tuple(f"{start + i * step:.{digits}f}" for i in range(count + 1))


HINT_STYLES = ("none", "slight", "medium", "full")
WEIGHTS = ("400", "430", "450", "475", "500")


@dataclass(frozen=True)
class Setting:
    key: str
    group: str
    label: str
    choices: tuple[str, ...]
    default: str
    help: str
    needs: tuple[str, ...] = ()     # usable when any of these is available (packages, "shim")

    def step(self, value: str, delta: int) -> str:
        """The value delta places away, stopping at the ends of the list."""
        i = self.choices.index(value) + delta
        return self.choices[max(0, min(len(self.choices) - 1, i))]


SETTINGS: tuple[Setting, ...] = (
    # Rendering: fontconfig (every app) and gsettings (GTK, Chromium UI).
    Setting("antialias", "Rendering", "Antialiasing", ("grayscale", "rgb", "bgr"), "grayscale",
            "grayscale: no colour fringes. rgb/bgr: subpixel, uses the panel's colour stripes."),
    Setting("hinting", "Rendering", "Hinting", HINT_STYLES, "slight",
            "Grid fitting for proportional text. slight only snaps vertically and keeps spacing."),
    Setting("mono_hinting", "Rendering", "Hinting, monospace", HINT_STYLES, "slight",
            "Same, for monospace fonts (terminal). Kept separate so the terminal stays stable."),
    Setting("lcdfilter", "Rendering", "LCD filter", ("default", "light", "legacy", "none"), "light",
            "Subpixel colour filter. FreeType apps only (GTK, terminal); Chromium ignores it."),
    # Fonts: files built and installed into ~/.local/share/fonts/fontlab.
    Setting("darkening", "Fonts", "Darkening", steps(0, 1, 0.05, 2), "0.00",
            "macOS-style stem darkening baked into Inter and Adwaita Sans. 1 = macOS strength.",
            needs=("inter", "adwaita")),
    Setting("ui_weight", "Fonts", "UI font weight", WEIGHTS, "400",
            "Weight of Inter and Adwaita Sans Regular/Italic. 400 = stock.", needs=("inter", "adwaita")),
    Setting("mono_weight", "Fonts", "JetBrains Mono weight", WEIGHTS, "400",
            "Weight of JetBrains Mono Regular/Italic. Open a new terminal window to see it.",
            needs=("jbm",)),
    Setting("sf_weight", "Fonts", "SF Pro Text weight", WEIGHTS, "400",
            "Weight of SF Pro Text Regular/Italic, used when web fonts = sf.", needs=("sf",)),
    Setting("web_fonts", "Fonts", "Web and UI sans font", ("default", "inter", "sf", "windows"), "default",
            "What sans-serif, system-ui, Arial etc. become. default: your system's choice. "
            "windows: Chromium uses Windows 11 fonts, other apps keep Inter."),
    # Chromium: Skia text contrast and gamma (web pages via the shim, browser UI via wrapper flags).
    Setting("contrast", "Chromium", "Text contrast", steps(0, 1, 0.1, 1), "0.0",
            "Skia text contrast. 0 = linear coverage.", needs=("shim",)),
    Setting("gamma", "Chromium", "Text gamma", steps(1, 2.2, 0.1, 1), "1.4",
            "Skia text gamma. Higher = heavier light-on-dark text, but it depends on text colour only.",
            needs=("shim",)),
    # System: needs sudo and a new login.
    Setting("freetype_darkening", "System", "FreeType stem darkening", ("keep", "off", "cff", "all"),
            "keep", "FREETYPE_PROPERTIES in /etc/environment (GTK, Qt, terminals). keep: fontlab leaves it "
            "alone. off: FreeType default. cff: OpenType CFF fonts. all: also the autofitter. "
            "Needs sudo and a new login."),
)

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}
DEFAULTS: dict[str, str] = {s.key: s.default for s in SETTINGS}
