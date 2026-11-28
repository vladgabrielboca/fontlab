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
            "Grid fitting for proportional text in GTK, Qt, terminals and Firefox. slight only snaps "
            "vertically and keeps spacing; full snaps to whole pixels and looks like Windows, if the font "
            "carries hints. Chromium keeps its own value."),
    Setting("mono_hinting", "Rendering", "Hinting, monospace", HINT_STYLES, "slight",
            "Same, for monospace fonts (terminal). Kept separate so the terminal stays stable."),
    Setting("lcdfilter", "Rendering", "LCD filter", ("default", "light", "legacy", "none"), "light",
            "Subpixel colour filter. FreeType apps only (GTK, terminal); Chromium ignores it."),
    Setting("small_bold", "Rendering", "Fake bold under 14px", ("off", "on"), "off",
            "fontconfig's synthetic bold for text smaller than 14 pixels. GTK apps use it; "
            "Chromium and Qt ignore it. Icon fonts are left out."),
    # Fonts: files built and installed into ~/.local/share/fonts/fontlab.
    Setting("darkening", "Fonts", "Darkening", steps(0, 1, 0.05, 2), "0.00",
            "macOS-style stem darkening baked into Inter, Adwaita Sans and Roboto. 1 = macOS strength.",
            needs=("inter", "adwaita", "roboto")),
    Setting("ui_weight", "Fonts", "UI font weight", WEIGHTS, "400",
            "Weight of Inter, Adwaita Sans and Roboto Regular/Italic. 400 = stock.",
            needs=("inter", "adwaita", "roboto")),
    Setting("mono_weight", "Fonts", "JetBrains Mono weight", WEIGHTS, "400",
            "Weight of JetBrains Mono Regular/Italic. Open a new terminal window to see it.",
            needs=("jbm",)),
    Setting("sf_weight", "Fonts", "SF Pro Text weight", WEIGHTS, "400",
            "Weight of SF Pro Text Regular/Italic, used when web fonts = sf.", needs=("sf",)),
    Setting("web_fonts", "Fonts", "Web and UI sans font", ("system", "inter", "sf", "windows"), "system",
            "What sans-serif, system-ui, Arial etc. become. system: your distro's choice. "
            "windows: Chromium uses Windows 11 fonts, other apps keep Inter."),
    Setting("vencord_fonts", "Fonts", "Discord font (Vencord)", ("off", "on"), "on",
            "Vesktop and other Vencord clients: replace Discord's own font (gg sans) with your "
            "sans-serif and monospace, so the settings above reach Discord. Uses a marked block in "
            "Vencord's quickCss.css; off removes it. Restart the client to see it."),
    # Chromium: Skia text contrast and gamma (web pages via the shim, browser UI via wrapper flags).
    # The defaults are Chromium's own Linux values; at the defaults fontlab adds nothing.
    Setting("contrast", "Chromium", "Text contrast", steps(0, 1, 0.1, 1), "0.2",
            "Text contrast in Chromium and Electron apps. 0.2 is Chromium's own value.",
            needs=("shim",)),
    Setting("gamma", "Chromium", "Text gamma", steps(1, 2.2, 0.1, 1), "1.2",
            "Text gamma in Chromium and Electron apps. Higher = heavier light-on-dark text.",
            needs=("shim",)),
    Setting("chromium_lcd_filter", "Chromium", "Subpixel filter", ("stock", "box"), "stock",
            "Skia's LCD filter in Chromium and Electron apps, with antialiasing rgb or bgr. box: a 1-pixel "
            "filter like Windows ClearType, sharper than stock. The shim patches it in memory; restart the app.",
            needs=("shim",)),
    Setting("chromium_hinting", "Chromium", "Hinting, Chromium", HINT_STYLES, "slight",
            "Grid fitting in Chromium and Electron apps, all text including code blocks. Kept apart from "
            "hinting because Chromium and FreeType want opposite values: slight keeps subpixel spacing, "
            "full makes Chromium's glyphs land wrong. Writes nothing when hinting and mono_hinting equal it."),
    Setting("session_shim", "Chromium", "Session-wide shim", ("off", "on"), "off",
            "Add the shim to LD_PRELOAD in ~/.config/uwsm/env and systemd --user so Chromium, Electron "
            "and AppImages launched from keybinds or terminals get contrast, gamma and system-ui. "
            "Needs a new login.",
            needs=("shim",)),
    # System: needs sudo and a new login.
    Setting("freetype_darkening", "System", "FreeType stem darkening", ("keep", "off", "cff", "all", "strong"),
            "keep", "FREETYPE_PROPERTIES in /etc/environment (GTK, Qt, terminals). keep: fontlab leaves it "
            "alone. off: FreeType default. cff: OpenType CFF fonts. all: also the autofitter. "
            "strong: all drivers, autofitter darkening kept up to larger sizes (lucidglyph's values). "
            "Needs sudo and a new login."),
    Setting("qt_no_synth_bold", "System", "Qt: no synthetic bold", ("keep", "off", "on"), "keep",
            "QT_NO_SYNTHESIZED_BOLD=1 in /etc/environment. Fixes bold looking too heavy with variable "
            "fonts in some Qt versions. keep: fontlab leaves it alone. Needs sudo and a new login."),
)

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}
DEFAULTS: dict[str, str] = {s.key: s.default for s in SETTINGS}
