# Castlevania / Ryujinx shader translator: isolated Android experiment

**Experimental only.** This does not replace ScarletNX's Vulkan renderer or change
the 1152-block Castlevania AOT module. The working boot and Mario's stable
branch/APK remain untouched. No ROM, XCI, keys, dumps, or captured shader data
belong in Git.

## Verified architecture

- ScarletNX pin: `34853eeae5af132e320adbb0193f13344085bf89`.
  `src/nx/gpu/shader/spirv_translate.c` translates Maxwell directly to SPIR-V,
  using a register reaching-definition tracker.
- `seedds/nxnative` vendors Ryujinx 1.3.2's MIT-licensed
  `Ryujinx.Graphics.Shader`, `Ryujinx.Common` and `Spv.Generator`.
  It includes a `BindlessElimination` change to follow phi cycles and
  equivalent OR operations on handles.
- `nxnative/dm/gfx/tools/dmsh_xlate` is a **C# .NET 10 offline shader
  translator** which outputs Vulkan SPIR-V and JSON reflection. Its
  Mac/iOS pipeline later converts SPIR-V to Metal. We use only the
  Maxwell-to-SPIR-V comparison, never the Metal part.
- ScarletNX's `SNX_SHADER_CORPUS` format (`src/nx/gpu/shader/corpus.c`)
  records a 24-byte `SNXS` v1 header, its private `ShaderInfo` and the
  original Maxwell shader bytecode. Graphics shaders include the 80-byte
  program header. `dmsh_xlate` can read that bytecode directly as a probe.
- Ryujinx needs facts not fully captured by SNXS (`c1` jump tables,
  texture dimensions, image formats, input/output formats). And the two
  renderers use incompatible descriptor/reflection layouts. A successful
  offline translation **does not mean its SPIR-V can be loaded as a
  ScarletNX shader**.

## Phase 1: capture shader corpus directly in the Android test APK

The **Castlevania experimental launcher** now exposes:

1. `Capturar shaders na proxima execucao` (default OFF). When ON,
   its SDL runtime receives `--diag=1` and ScarletNX writes its private
   `captures/shaders/*.snxs` files. Capture may increase disk usage.
2. `Exportar shaders de fragmento (.zip)`. This uses Android's
   `ACTION_CREATE_DOCUMENT` and zips only files named
   `<16 hex digits>_4.snxs` under its game's private capture directory.
   It never reads, zips, or exports XCI, prod.keys, save data, or other
   private app files. Leave the game and return to the launcher to export.

Build (preserves AOT and cached dependencies):

```bash
cd "$HOME/LASRecomp-Android" || exit 1
git pull --ff-only origin experimental/castlevania-belmonts-curse
python3 -m unittest discover -s tests -p test_castlevania_ryujinx_probe.py
bash compilar-castlevania-shader-termux.sh
```

Install the resulting experimental APK, turn capture ON, reproduce the scene
with missing graphics, return to the launcher and export the ZIP into
Downloads via the system picker.

## Phase 2: prepare a Ryujinx translation job (Termux)

The exported ZIP and the derived Maxwell binaries remain **local**.
```bash
mkdir -p "$HOME/castlevania-shader-corpus"
unzip -o "/storage/emulated/0/Download/Castlevania-shaders-SNXS.zip" \
  -d "$HOME/castlevania-shader-corpus"
cd "$HOME/LASRecomp-Android" || exit 1
python3 tools/castlevania_ryujinx_probe.py \
  "$HOME/castlevania-shader-corpus/shaders" \
  --out "$HOME/castlevania-ryujinx-probe"
```

`jobs.json` is written with `stage: "ps"` and the original Maxwell code
as separate `.bin` files. `errors.txt` reports malformed or unsupported
captures; never force them through the translator. This stage needs only
Python 3, not dotnet or a new Android compilation.

## Phase 3: run the isolated translation (computer with .NET SDK 10)

```bash
git clone --depth 1 https://github.com/seedds/nxnative "$HOME/nxnative"
python3 tools/castlevania_ryujinx_probe.py \
  "$HOME/castlevania-shader-corpus/shaders" \
  --out "$HOME/castlevania-ryujinx-probe" \
  --nxnative "$HOME/nxnative"
```

The tool delegates to `dotnet run --project
<nxnative>/dm/gfx/tools/dmsh_xlate/dmsh_xlate.csproj -- jobs.json out/spirv`.
Use `spirv-val` to validate translated binaries. Missing fact-table
entries can cause bad translation or misleading failures; this is a
**diagnostic compatibility test**, not game-ready SPIR-V.

The current Termux phone environment is **not assumed to have .NET SDK 10**.
Its portable Python preparation step works independently. Running the
.NET translator can occur on a Linux/Windows computer; do not upload a
full game or private keys to GitHub.

## Criteria to continue

Compare the five known fragment shaders with
`untracked texture handle` in the Castlevania log. If Ryujinx emits
valid SPIR-V for them, investigate reflection/resource mapping and
whether the handles are constant, OR-combined, or phi-mediated.
Only then attempt a separate runtime adaptation behind an opt-in flag.
The direct ScarletNX shader translator stays available as fallback.

If Ryujinx fails on the same shaders, do not graft it into the APK;
check missing texture facts, its bindless log, and consider targeted
flow-sensitive ScarletNX repairs.

References:

- https://github.com/seedds/nxnative/blob/main/dm/third_party/ryujinx/README.md
- https://github.com/seedds/nxnative/blob/main/dm/gfx/tools/dmsh_xlate/Program.cs
- https://github.com/scarletnx/ScarletNX/blob/34853eeae5af132e320adbb0193f13344085bf89/src/nx/gpu/shader/corpus.c
