"""Heavier Regular/Italic faces made by instancing variable fonts.

Each result keeps the name table and style bits of the stock static face it replaces,
so apps still see it as "<Family> Regular". Ported from fontations-weight-fix.
"""

import os

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from hinting import drop_hinting, is_hinted


def _take_identity(inst, static, extra_os2=()):
    """Give an instanced font the names and style bits of a stock static face."""
    inst["name"] = static["name"]
    for k in ("usWeightClass", "fsSelection", *extra_os2):
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


# --- Inter --------------------------------------------------------------------------

def inter(release_dir, out_dir, weights):
    """release_dir: the unzipped Inter 4.x release (InterVariable*.ttf, extras/ttf/)."""
    pairs = (("InterVariable.ttf", "Inter-Regular.ttf"), ("InterVariable-Italic.ttf", "Inter-Italic.ttf"))
    for w in weights:
        os.makedirs(os.path.join(out_dir, str(w)), exist_ok=True)
        for var, static in pairs:
            inst = instance(os.path.join(release_dir, var), {"wght": w, "opsz": 14})
            _take_identity(inst, TTFont(os.path.join(release_dir, "extras", "ttf", static)), ("achVendID",))
            inst.save(os.path.join(out_dir, str(w), static))


# --- JetBrains Mono -----------------------------------------------------------------
# The system file (often a Nerd Font patch) stays the base, so icons and every table
# the patcher added are kept. Only the glyphs the official variable font also has get
# heavier outlines. Hinting is dropped: the old instructions do not fit the new outlines.

def jetbrains_mono(base_regular, base_italic, variable_dir, out_dir, weights):
    pairs = ((base_regular, "JetBrainsMono[wght].ttf"), (base_italic, "JetBrainsMono-Italic[wght].ttf"))
    for w in weights:
        os.makedirs(os.path.join(out_dir, str(w)), exist_ok=True)
        for base_path, var in pairs:
            donor = instantiateVariableFont(TTFont(os.path.join(variable_dir, var)), {"wght": w})
            base = TTFont(base_path)
            bg, dg = base["glyf"], donor["glyf"]
            for name in donor.getGlyphOrder():
                if name in bg.glyphs:
                    g = dg[name]
                    g.expand(dg)
                    bg[name] = g
                    base["hmtx"][name] = donor["hmtx"][name]
            drop_hinting(base)
            base.save(os.path.join(out_dir, str(w), os.path.basename(base_path)))

