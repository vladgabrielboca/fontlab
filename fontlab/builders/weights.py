"""Heavier Regular/Italic faces made from variable fonts.

"instance": a static instance that keeps the name table and style bits of the stock
static face it replaces, so apps still see it as "<Family> Regular".
"graft": the stock file stays the base (often a Nerd Font patch), so icons and every
table the patcher added are kept; only glyphs the variable font also has get its
outlines. Hinting is dropped: the old instructions do not fit the new outlines.
"""

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from hinting import drop_hinting, is_hinted


def _take_identity(inst, static):
    """Give an instanced font the names and style bits of a stock static face."""
    inst["name"] = static["name"]
    for k in ("usWeightClass", "fsSelection", "achVendID"):
        setattr(inst["OS/2"], k, getattr(static["OS/2"], k))
    inst["head"].macStyle = static["head"].macStyle
    for t in ("STAT", "avar"):
        if t in inst:
            del inst[t]


def instance(vf_path, loc):
    """Static instance of a variable font at loc. A hinted variable font without `cvar`
    carries instructions for its default master only, so other instances lose them."""
    vf = TTFont(vf_path)
    keep = is_hinted(vf) and ("cvar" in vf or all(
        loc.get(a.axisTag, a.defaultValue) == a.defaultValue for a in vf["fvar"].axes))
    f = instantiateVariableFont(vf, loc)
    if is_hinted(f) and not keep:
        drop_hinting(f)
    return f


def at_weight(base, variable, method, axes, wght):
    """The face `base` rebuilt at weight wght from `variable`."""
    if method == "instance":
        f = instance(variable, {**axes, "wght": wght})
        _take_identity(f, TTFont(base))
        return f
    if method == "graft":
        donor = instantiateVariableFont(TTFont(variable), {**axes, "wght": wght})
        f = TTFont(base)
        bg, dg = f["glyf"], donor["glyf"]
        for name in donor.getGlyphOrder():
            if name in bg.glyphs:
                g = dg[name]
                g.expand(dg)
                bg[name] = g
                f["hmtx"][name] = donor["hmtx"][name]
        drop_hinting(f)
        return f
    raise ValueError(f"unknown method {method}")
