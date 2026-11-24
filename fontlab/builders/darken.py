"""macOS-style stem darkening baked into TrueType outlines.

Every outline edge moves outward by xem (horizontal) and yem (vertical) em per side.
Advances stay the same, like macOS. The point shifting is FreeType's
FT_Outline_EmboldenXY algorithm. macOS 10.13 factors (reverse-engineered by Pathfinder):
0.0121 em horizontal, 0.0121 * 1.25 em vertical, exact below ~25 px.
"""

import math

from fontTools.ttLib import TTFont


def signed_area(pts):
    return sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts))) / 2


def embolden_contour(pts, outer_cw, xs, ys):
    n = len(pts)
    out = []
    lmin = min(xs, ys)
    for i in range(n):
        p = pts[i]
        j = (i - 1) % n
        while pts[j] == p and j != i:
            j = (j - 1) % n
        k = (i + 1) % n
        while pts[k] == p and k != i:
            k = (k + 1) % n
        if j == i or k == i:
            out.append(p)
            continue
        ix, iy = p[0] - pts[j][0], p[1] - pts[j][1]
        length = math.hypot(ix, iy)
        ix, iy = ix / length, iy / length
        ox, oy = pts[k][0] - p[0], pts[k][1] - p[1]
        length = math.hypot(ox, oy)
        ox, oy = ox / length, oy / length
        d = ix * ox + iy * oy
        if d <= -0.9375:          # near-reversal: FreeType leaves the point alone
            out.append(p)
            continue
        d += 1
        sx, sy = iy + oy, -ix - ox
        q = ox * iy - oy * ix
        if not outer_cw:          # TrueType outer contours run clockwise
            sx, sy, q = -sx, -sy, -q
        sx = sx * xs / d if xs * q <= lmin * d else sx * lmin / q
        sy = sy * ys / d if ys * q <= lmin * d else sy * lmin / q
        out.append((p[0] + sx, p[1] + sy))
    return out


def darken(src, dst, xem, yem):
    font = TTFont(src)
    if "fvar" in font:
        font.save(dst)
        return dst
    upem = font["head"].unitsPerEm
    xs, ys = xem * upem, yem * upem
    glyf, hmtx = font["glyf"], font["hmtx"]
    for name in font.getGlyphOrder():
        g = glyf[name]
        if g.numberOfContours <= 0:
            continue
        coords = g.coordinates
        pts = [tuple(c) for c in coords]
        contours, start = [], 0
        for end in g.endPtsOfContours:
            contours.append(pts[start:end + 1])
            start = end + 1
        outer_cw = sum(signed_area(c) for c in contours) < 0
        moved = [pt for c in contours for pt in embolden_contour(c, outer_cw, xs, ys)]
        for i, (x, y) in enumerate(moved):
            coords[i] = (round(x), round(y))
        g.recalcBounds(glyf)
        hmtx[name] = (hmtx[name][0], g.xMin)
    for name in font.getGlyphOrder():   # composites follow their changed components
        g = glyf[name]
        if g.isComposite():
            g.recalcBounds(glyf)
            hmtx[name] = (hmtx[name][0], g.xMin)
    font.save(dst)
    return dst

