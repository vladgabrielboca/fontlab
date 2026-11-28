"""The settings fontlab controls. Every value is a string picked from a fixed list,
so the TUI (left/right), the CLI (key=value) and the state file all work the same way.
"""

from __future__ import annotations

from dataclasses import dataclass


def steps(start: float, stop: float, step: float, digits: int) -> tuple[str, ...]:
    count = round((stop - start) / step)
    return tuple(f"{start + i * step:.{digits}f}" for i in range(count + 1))


HINT_STYLES = ("none", "slight", "medium", "full")
WEIGHTS = ("400", "430", "450", "475", "500")     # packages build every weight above 400


@dataclass(frozen=True)
class WebFont:
    """One web_fonts choice."""
    family: str | None      # what sans-serif, Arial etc. become in fontconfig (None: no rule)
    system_ui: str | None   # what CSS system-ui becomes in Chromium (None: the GTK UI font)
    package: str | None     # font package it needs


WEB_FONTS: dict[str, WebFont] = {
    "system": WebFont(None, None, None),
    "inter": WebFont("Inter", "Inter", "inter"),
    "windows": WebFont(None, "Segoe UI", "windows"),   # Chromium only; other apps keep Inter
}


SUBPIXEL = (("antialias", ("rgb", "bgr")),)


@dataclass(frozen=True)
class Setting:
    key: str
    group: str
    label: str
    choices: tuple[str, ...]
    default: str
    help: str               # what the choices do
    affects: str            # which apps see it, and what it takes to see a change
    needs: tuple[str, ...] = ()     # "shim" or "vencord". Font package needs come from
                                    # packages.py (weight_key, darkens).
    # The setting only does something when each (key, values) holds. Otherwise it is
    # locked and apply uses its default (availability.py).
    active_when: tuple[tuple[str, tuple[str, ...]], ...] = ()


SETTINGS: tuple[Setting, ...] = (
    # Rendering: fontconfig (every app) and gsettings (GTK, Chromium UI).
    Setting("antialias", "Rendering", "Antialiasing", ("grayscale", "rgb", "bgr"), "grayscale",
            "grayscale: no colour fringes. rgb/bgr: subpixel text, uses the panel's colour stripes; "
            "pick the order your panel has.",
            "every app"),
    Setting("hinting", "Rendering", "Hinting", HINT_STYLES, "slight",
            "Grid fitting for proportional text. slight only snaps vertically and keeps spacing. "
            "full snaps to whole pixels and looks like Windows, if the font carries hints.",
            "GTK, Qt, terminals, Firefox (Chromium has its own)"),
    Setting("mono_hinting", "Rendering", "Hinting, monospace", HINT_STYLES, "slight",
            "Grid fitting for monospace fonts, kept apart so the terminal stays stable.",
            "terminals and code editors (Chromium has its own)"),
    Setting("lcdfilter", "Rendering", "LCD filter", ("default", "light", "legacy", "none"), "light",
            "How much subpixel text is blurred to hide colour fringes. light: least blur that "
            "still hides them. none: sharpest, most fringes.",
            "GTK, Qt, terminals, Firefox (not Chromium)", active_when=SUBPIXEL),
    Setting("small_bold", "Rendering", "Fake bold under 14px", ("off", "on"), "off",
            "fontconfig's synthetic bold for text smaller than 14 pixels. Icon fonts are left out.",
            "GTK apps (Chromium and Qt ignore it)"),
    # Fonts: files built and installed into ~/.local/share/fonts/fontlab.
    Setting("darkening", "Fonts", "Darkening", steps(0, 1, 0.05, 2), "0.00",
            "macOS-style stem darkening baked into the font files. 1 = macOS strength.",
            "every app using Inter"),
    Setting("ui_weight", "Fonts", "UI font weight", WEIGHTS, "400",
            "Weight of the Regular and Italic faces. 400 = stock.",
            "every app using Inter"),
    Setting("mono_weight", "Fonts", "Monospace weight", WEIGHTS, "400",
            "Weight of the Regular and Italic faces. 400 = stock.",
            "JetBrains Mono; open a new terminal window to see it"),
    Setting("web_fonts", "Fonts", "Web and UI sans font", tuple(WEB_FONTS), "system",
            "What sans-serif, system-ui, Arial, Helvetica and Segoe UI become. system: your distro "
            "decides. inter: Inter. windows: Chromium uses the Windows 11 "
            "fonts, other apps get Inter.",
            "web pages and apps that ask for a generic sans font"),
    Setting("vencord_fonts", "Fonts", "Discord font (Vencord)", ("off", "on"), "on",
            "on: Discord's own font (gg sans) is replaced by your sans-serif and monospace, so the "
            "settings above reach Discord. Uses a marked block in Vencord's quickCss.css.",
            "Vesktop, Vencord, Equibop; restart the client", needs=("vencord",)),
    # Chromium: Skia text settings, added by the shim (preloaded into the whole login session).
    # The defaults are Chromium's own Linux values; at the defaults fontlab adds nothing.
    Setting("contrast", "Chromium", "Text contrast", steps(0, 1, 0.1, 1), "0.2",
            "Skia's text contrast. Higher = darker, crisper edges. 0.2 is Chromium's own value.",
            "Chromium and Electron apps; restart the app", needs=("shim",)),
    Setting("gamma", "Chromium", "Text gamma", steps(1, 2.2, 0.1, 1), "1.2",
            "Skia's text gamma. Higher = heavier light-on-dark text. 1.2 is Chromium's own value.",
            "Chromium and Electron apps; restart the app", needs=("shim",)),
    Setting("chromium_lcd_filter", "Chromium", "Subpixel filter", ("stock", "box"), "stock",
            "Skia's subpixel filter. box: a 1-pixel filter like Windows ClearType, sharper than "
            "stock. The shim patches it in memory.",
            "Chromium and Electron apps; restart the app", needs=("shim",), active_when=SUBPIXEL),
    Setting("chromium_hinting", "Chromium", "Hinting, Chromium", HINT_STYLES, "slight",
            "Grid fitting for all Chromium text, code blocks included. Kept apart because Chromium "
            "and FreeType want opposite values: slight keeps subpixel spacing, full makes glyphs "
            "land wrong.",
            "Chromium and Electron apps; restart the app", needs=("shim",)),
    # System: needs sudo and a new login.
    Setting("freetype_darkening", "System", "FreeType stem darkening", ("keep", "off", "cff", "all", "strong"),
            "keep", "FREETYPE_PROPERTIES in /etc/environment. keep: fontlab leaves it alone. off: FreeType "
            "default. cff: OpenType CFF fonts. all: also the autofitter. strong: all drivers, darkening "
            "kept up to larger sizes (lucidglyph's values).",
            "GTK, Qt, terminals, Firefox; needs sudo (!) and a new login"),
    Setting("qt_no_synth_bold", "System", "Qt: no synthetic bold", ("keep", "off", "on"), "keep",
            "QT_NO_SYNTHESIZED_BOLD=1 in /etc/environment. Fixes bold looking too heavy with variable "
            "fonts in some Qt versions. keep: fontlab leaves it alone.",
            "Qt apps; needs sudo (!) and a new login"),
)

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}
DEFAULTS: dict[str, str] = {s.key: s.default for s in SETTINGS}
