"""Heavier Regular/Italic faces made by instancing variable fonts.

Each result keeps the name table and style bits of the stock static face it replaces,
so apps still see it as "<Family> Regular". Ported from fontations-weight-fix
(Inter, Adwaita Sans) and the SF build script.
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


# --- Adwaita Sans -------------------------------------------------------------------
# Adwaita Sans ships as one variable file per slant. A heavier static Regular cannot sit
# next to the stock variable file: its named instances carry an opsz range (14-32) that
# fontconfig penalises at 11pt, and Bold requests then fall back to the static Regular.
# So the whole family is built as static files and the variable files are hidden.

ADWAITA = {"AdwaitaSans-Regular.ttf": False, "AdwaitaSans-Italic.ttf": True}
RIBBI = ("Regular", "Italic", "Bold", "Bold Italic")


def _static_names(f, family_name, ps_prefix, style, wclass, italic, path):
    n = f["name"]
    for nid in (16, 17, 21, 22, 25):
        n.removeNames(nameID=nid)
    family = family_name if style in RIBBI else family_name + " " + style.replace(" Italic", "")
    sub = style if style in RIBBI else ("Italic" if italic else "Regular")
    for nid, s in ((1, family), (2, sub), (4, f"{family_name} {style}"),
                   (6, f"{ps_prefix}-{style.replace(' ', '')}"), (16, family_name), (17, style)):
        n.setName(s, nid, 3, 1, 0x409)
    os2 = f["OS/2"]
    os2.usWeightClass = wclass
    bold = style in ("Bold", "Bold Italic")
    os2.fsSelection = ((os2.fsSelection & ~0b1100001) | (1 if italic else 0)
                       | (0b100000 if bold else 0) | (0b1000000 if not italic and not bold else 0))
    f["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)
    for t in ("STAT", "avar"):
        if t in f:
            del f[t]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f.save(path)


def adwaita(system_dir, out_dir, weights):
    """<out>/400: every named instance as a static file. <out>/<w>: Regular/Italic at w."""
    for src, italic in ADWAITA.items():
        path = os.path.join(system_dir, src)
        for inst in TTFont(path)["fvar"].instances:
            style = TTFont(path)["name"].getDebugName(inst.subfamilyNameID)
            loc = dict(inst.coordinates, opsz=14)
            f = instance(path, loc)
            _static_names(f, "Adwaita Sans", "AdwaitaSans", style, int(loc["wght"]), italic,
                          os.path.join(out_dir, "400", f"AdwaitaSans-{style.replace(' ', '')}.ttf"))
        for w in weights:
            f = instance(path, {"wght": w, "opsz": 14})
            _static_names(f, "Adwaita Sans", "AdwaitaSans", "Italic" if italic else "Regular",
                          400, italic, os.path.join(out_dir, str(w), src))


# --- Roboto, Ubuntu Sans, Ubuntu Sans Mono ------------------------------------------
# Normal-width (wdth=100) named instances as static files, plus heavier Regular/Italic.

def static_family(regular_vf, italic_vf, family, ps_prefix, out_dir, weights):
    """<out>/400: normal-width named instances. <out>/<w>: Regular/Italic at w.
    Fonts without a wdth axis (Ubuntu Sans Mono) only get wght pinned."""
    for path, italic in ((regular_vf, False), (italic_vf, True)):
        meta = TTFont(path)
        axes = {a.axisTag for a in meta["fvar"].axes}
        for inst in meta["fvar"].instances:
            loc = dict(inst.coordinates)
            if loc.get("wdth", 100.0) != 100.0:
                continue
            style = meta["name"].getDebugName(inst.subfamilyNameID)
            f = instance(path, loc)
            _static_names(f, family, ps_prefix, style, int(round(loc["wght"])), italic,
                          os.path.join(out_dir, "400", f"{ps_prefix}-{style.replace(' ', '')}.ttf"))
        for w in weights:
            style = "Italic" if italic else "Regular"
            loc = {"wght": w, **({"wdth": 100.0} if "wdth" in axes else {})}
            f = instance(path, loc)
            _static_names(f, family, ps_prefix, style, 400, italic,
                          os.path.join(out_dir, str(w), f"{ps_prefix}-{style}.ttf"))


def roboto(regular_vf, italic_vf, out_dir, weights):
    static_family(regular_vf, italic_vf, "Roboto", "Roboto", out_dir, weights)


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


# --- SF Pro Text --------------------------------------------------------------------

def sf_pro_text(variable_dir, static_dir, out_dir, weights):
    """Text optical size (opsz 17), named like the stock SF Pro Text Regular/Italic."""
    faces = (("SF-Pro.ttf", {"wdth": 100, "opsz": 17}, "SF-Pro-Text-Regular"),
             ("SF-Pro-Italic.ttf", {"opsz": 17, "YAXS": 400}, "SF-Pro-Text-RegularItalic"))
    for w in weights:
        os.makedirs(os.path.join(out_dir, str(w)), exist_ok=True)
        for var, axes, static in faces:
            vf = TTFont(os.path.join(variable_dir, var))
            axes = {k: v for k, v in axes.items() if k in {a.axisTag for a in vf["fvar"].axes}}
            inst = instantiateVariableFont(vf, {**axes, "wght": float(w)}, updateFontNames=False)
            _take_identity(inst, TTFont(os.path.join(static_dir, static + ".otf")))
            inst.save(os.path.join(out_dir, str(w), static + ".ttf"))
