#!/usr/bin/env python3
"""Give the open-source fallback font a drawable U+25A1 white-square glyph.

No Nintendo font or game files are read. Roboto-Medium.ttf is Apache-2.0
and already included with the Dear ImGui third-party files.
"""
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: android-font-fallback.py SOURCE.ttf OUTPUT.ttf")
    src, dst = sys.argv[1:]
    font = TTFont(src)
    if "glyf" not in font or "hmtx" not in font:
        raise SystemExit("ERROR: expected a TrueType font with glyf outlines")
    if 0x25A1 not in (font.getBestCmap() or {}):
        glyph = "las_white_square"
        if glyph in font.getGlyphOrder():
            raise SystemExit("ERROR: fallback glyph name already exists")
        upem = font["head"].unitsPerEm
        left, bottom = int(upem * .12), int(upem * .04)
        right, top = int(upem * .88), int(upem * .80)
        border = max(1, int(upem * .10))
        pen = TTGlyphPen(None)
        for i, point in enumerate(((left, bottom), (left, top),
                                   (right, top), (right, bottom))):
            if not i: pen.moveTo(point)
            else: pen.lineTo(point)
        pen.closePath()
        for i, point in enumerate(((left+border, bottom+border),
                                   (right-border, bottom+border),
                                   (right-border, top-border),
                                   (left+border, top-border))):
            if not i: pen.moveTo(point)
            else: pen.lineTo(point)
        pen.closePath()
        font.setGlyphOrder(font.getGlyphOrder() + [glyph])
        font["glyf"][glyph] = pen.glyph()
        font["hmtx"][glyph] = (upem, left)
        font["maxp"].numGlyphs = len(font.getGlyphOrder())
        count = 0
        for table in font["cmap"].tables:
            if table.isUnicode() and table.format in (4, 12):
                table.cmap[0x25A1] = glyph
                count += 1
        if count == 0:
            raise SystemExit("ERROR: Unicode cmap not found")
        print(f"Added white square U+25A1 in {count} cmap tables")
    font.save(dst)
    check = TTFont(dst)
    mapped = (check.getBestCmap() or {}).get(0x25A1)
    if not mapped or mapped == ".notdef" or check["glyf"][mapped].numberOfContours != 2:
        raise SystemExit("ERROR: U+25A1 not drawable in resulting font")
    if (check.getBestCmap() or {}).get(0x2011) is None:
        raise SystemExit("ERROR: an existing glyph was lost")
    print(f"Validated Android font: U+25A1 -> {mapped}")


if __name__ == "__main__":
    main()
