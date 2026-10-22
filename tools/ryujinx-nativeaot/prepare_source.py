#!/usr/bin/env python3
"""Prepare the actual nxnative/Ryujinx C# shader translator for native Android AOT.

Only the 'partial' modifier changes on a local temporary copy of Program.cs.
Upstream C# sources stay in nxnative; no extracted game assets are committed.
"""
import argparse
import hashlib
import json
from pathlib import Path
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
    # The NativeAOT ABI supplies the live GPU facts, rather than nxnative's
    # offline answer-table defaults. These hooks affect ABI 2 only.
    hooks = {
        'readonly byte[] _c1;': '''readonly byte[] _c1;
        public Func<int, uint>? RuntimeConstant;
        public Func<int, int, SamplerType>? RuntimeSampler;
        public Func<int, int, bool>? RuntimeNormalized;''',
        'public uint ConstantBuffer1Read(int offset) {':
            'public uint ConstantBuffer1Read(int offset) { if (RuntimeConstant != null) return RuntimeConstant(offset);',
        'public SamplerType QuerySamplerType(int handle, int cbufSlot = -1)\n        {':
            '''public SamplerType QuerySamplerType(int handle, int cbufSlot = -1)
        {
            if (RuntimeSampler != null) return RuntimeSampler(handle, cbufSlot);''',
        'public TextureFormat QueryTextureFormat(int handle, int cbufSlot = -1)':
            '''public bool QueryTextureCoordNormalized(int handle, int cbufSlot = -1) =>
            RuntimeNormalized?.Invoke(handle, cbufSlot) ?? true;
        public TextureFormat QueryTextureFormat(int handle, int cbufSlot = -1)''',
    }
    if (srcdir / 'ScarletAdapterV2.cs').exists():
        hooks['false, 1f, AlphaTestOp.Always, 0f'] = 'false, 1f, (AlphaTestOp)(_job["alpha_func"]?.GetValue<int>() ?? 8), _job["alpha_reference"]?.GetValue<float>() ?? 0f'
        for old, new in hooks.items():
            if code.count(old) != 1:
                raise ValueError('upstream accessor changed: ' + old)
            code = code.replace(old, new, 1)
    outdir.mkdir(parents=True, exist_ok=True)
    destination = outdir / "Program.Native.cs"
    if not destination.exists() or destination.read_text(encoding="utf-8") != code:
        destination.write_text(code, encoding="utf-8")
    files = ["BridgeExports.cs", "ScarletAdapter.cs", "RyujinxShaderNative.csproj"]
    if (srcdir / 'ScarletAdapterV2.cs').exists():
        files.append('ScarletAdapterV2.cs')
    digest = hashlib.sha256(code.encode())
    for filename in files:
        source = (srcdir / filename).read_bytes()
        digest.update(filename.encode() + b'\0' + source)
        target = outdir / filename
        if not target.exists() or target.read_bytes() != source:
            target.write_bytes(source)
    identity = 'SNX_RYU_SOURCE_SHA256=' + digest.hexdigest()
    (outdir / 'BuildIdentity.g.cs').write_text('''// Generated from every adapter input; never restored from a binary cache.
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
static unsafe partial class SwshXlate {
    private static readonly byte* SourceIdentity = Owned("''' + identity + '''"u8);
    [UnmanagedCallersOnly(EntryPoint = "snx_ryu_build_identity", CallConvs = new[] { typeof(CallConvCdecl) })]
    public static byte* BuildIdentity() => SourceIdentity;
}
''')
    (outdir / 'build-identity.json').write_text(json.dumps({'source_identity': identity}, indent=2) + '\n')
    print(identity)
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
