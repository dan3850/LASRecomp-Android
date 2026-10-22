#!/usr/bin/env python3
"""Prepare the actual nxnative/Ryujinx C# shader translator for native Android AOT.

Only the 'partial' modifier changes on a local temporary copy of Program.cs.
Upstream C# sources stay in nxnative; no extracted game assets are committed.
"""
import argparse
from pathlib import Path
import shutil
import sys


def prepare(nxnative: Path, srcdir: Path, outdir: Path):
    original = nxnative / "dm/gfx/tools/dmsh_xlate/Program.cs"
    ryu = nxnative / "dm/third_party/ryujinx"
    csproj = ryu / "src/Ryujinx.Graphics.Shader/Ryujinx.Graphics.Shader.csproj"
    if not original.is_file() or not csproj.is_file():
        raise ValueError("nxnative clone incomplete (dmsh_xlate + vendored Ryujinx required)")
    code = original.read_text(encoding="utf-8")
    marker = "static class SwshXlate"
    if code.count(marker) != 1 or "sealed class Accessor : IGpuAccessor" not in code:
        raise ValueError("upstream Ryujinx launcher changed: inspect source before adapting")
    code = code.replace(marker, "static partial class SwshXlate", 1)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "Program.Native.cs").write_text(code, encoding="utf-8")
    for filename in ("BridgeExports.cs", "RyujinxShaderNative.csproj"):
        shutil.copyfile(srcdir / filename, outdir / filename)
    print("NativeAOT source staged in", outdir)
    print("Ryujinx source:", ryu)
    print("No game-derived shader data, APK, or AOT changed.")
    return outdir


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nxnative", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        prepare(args.nxnative.expanduser().resolve(), Path(__file__).resolve().parent,
                args.out.expanduser().resolve())
    except (OSError, ValueError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
