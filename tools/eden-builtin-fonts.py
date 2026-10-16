#!/usr/bin/env python3
"""Extract Eden's built-in Switch-compatible fallback TTFs for private Android builds.

Eden's font data files are SPDX-License-Identifier: GPL-2.0-or-later, originally
Copyright 2019 yuzu Emulator Project. Keep these terms and attribution when
distributing an APK containing the resulting font bytes. These are emulator
fallback fonts, not dumps from a Nintendo console.

The caller downloads two PINNED upstream *.cpp source files. This script only
turns their hexadecimal arrays back into TTF assets and validates the result.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import re

from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen

EXPECTED = {
    "FONT_STANDARD": 217276,
    "FONT_NINTENDO_EXTENDED": 6024,
}


def extract_font(source: Path, array_name: str, destination: Path) -> None:
    content = source.read_text(encoding="utf-8")
    start = content.find(array_name + "{{")
    if start < 0:
        raise ValueError(f"{source}: array {array_name} not found")
    start += len(array_name) + 2
    end = content.find("}};", start)
    if end < 0:
        raise ValueError(f"{source}: array {array_name} end not found")
    payload = content[start:end]
    values = re.findall(r"0x([0-9a-fA-F]{2})(?![0-9a-fA-F])", payload)
    data = bytes(int(v, 16) for v in values)
    if len(data) != EXPECTED[array_name]:
        raise ValueError(f"{array_name}: expected {EXPECTED[array_name]} bytes, got {len(data)}")
    if data[:4] != b"\x00\x01\x00\x00":
        raise ValueError(f"{array_name}: expected a classic TrueType sfnt, got {data[:4].hex()}")
    with TTFont(BytesIO(data), recalcBBoxes=False, recalcTimestamp=False) as font:
        font.ensureDecompiled()
        if "glyf" not in font or "cmap" not in font or not font.getBestCmap():
            raise ValueError(f"{array_name}: missing TrueType outlines or unicode cmap")
        # Link's Awakening uses the empty-square fallback codepoint.
        # Keep this compatibility glyph without requiring a Nintendo font.
        if array_name == "FONT_STANDARD" and 0x25A1 not in font.getBestCmap():
            glyph = "lasrecomp_white_square"
            upem = font["head"].unitsPerEm
            left, bottom = int(upem * .12), int(upem * .04)
            right, top = int(upem * .88), int(upem * .80)
            border = max(1, int(upem * .10))
            pen = TTGlyphPen(None)
            for contour in (
                [(left, bottom), (left, top), (right, top), (right, bottom)],
                [(left+border, bottom+border), (right-border, bottom+border),
                 (right-border, top-border), (left+border, top-border)],
            ):
                pen.moveTo(contour[0])
                for pt in contour[1:]:
                    pen.lineTo(pt)
                pen.closePath()
            font.setGlyphOrder(font.getGlyphOrder() + [glyph])
            font["glyf"][glyph] = pen.glyph()
            font["hmtx"][glyph] = (upem, left)
            font["maxp"].numGlyphs = len(font.getGlyphOrder())
            found = 0
            for cmap in font["cmap"].tables:
                if cmap.isUnicode() and cmap.format in (4, 12):
                    cmap.cmap[0x25A1] = glyph
                    found += 1
            if not found:
                raise ValueError(f"{array_name}: cannot add unicode fallback glyph")
            output = BytesIO()
            font.save(output)
            data = output.getvalue()
        print(f"{array_name}: {len(data)} bytes, {len(font.getBestCmap())} mapped glyphs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--standard-source", type=Path, required=True)
    parser.add_argument("--extended-source", type=Path, required=True)
    parser.add_argument("--standard-output", type=Path, required=True)
    parser.add_argument("--extended-output", type=Path, required=True)
    args = parser.parse_args()
    extract_font(args.standard_source, "FONT_STANDARD", args.standard_output)
    extract_font(args.extended_source, "FONT_NINTENDO_EXTENDED", args.extended_output)


if __name__ == "__main__":
    main()
