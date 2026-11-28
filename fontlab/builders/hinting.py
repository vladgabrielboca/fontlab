"""TrueType hinting that no longer fits the outlines.

TrueType instructions are written for one set of outlines: the CVT holds that design's
stem widths, and glyph programs move its points. Once the outlines change (darkening,
a weight instance of a variable font without `cvar`), the old program can snap stems
back to the old widths at hintstyle full. Dropping it leaves the outlines as built.
"""

from fontTools.ttLib.tables import ttProgram


def is_hinted(font):
    """Has instructions that encode a design (functions, control values). A lone `prep`
    (JetBrains Mono's variable fonts: dropout control and smoothing flags) does not."""
    return "fpgm" in font or "cvt " in font


def drop_hinting(font):
    """Remove all TrueType instructions and mark the font for smoothing without grid fitting."""
    for t in ("fpgm", "prep", "cvt ", "cvar", "hdmx", "LTSH", "VDMX"):
        if t in font:
            del font[t]
    if "gasp" in font:
        font["gasp"].gaspRange = {0xFFFF: 0x000A}   # smooth, no grid fitting
    if "glyf" in font:
        glyf = font["glyf"]
        for name in font.getGlyphOrder():
            g = glyf[name]
            if g.numberOfContours != 0 and hasattr(g, "program"):
                g.program = ttProgram.Program()
                g.program.fromBytecode(b"")
    if "maxp" in font and font["maxp"].tableVersion >= 0x00010000:
        m = font["maxp"]
        m.maxZones, m.maxTwilightPoints, m.maxStorage = 1, 0, 0
        m.maxFunctionDefs = m.maxInstructionDefs = m.maxStackElements = m.maxSizeOfInstructions = 0
