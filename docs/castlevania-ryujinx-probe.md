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

## Phase 2: translate on the same Android phone using Termux

A current Termux ARM64 repository provides \`dotnet-sdk-10.0\` (confirmed
2026-10-22). The nxnative tool targets \`net10.0\`. This experiment therefore
does **not** require a PC or a Linux emulator. It does require space for the
SDK, restore packages and a small sparse checkout of the Ryujinx translator.

From the experimental source branch:

\`\`\`bash
cd "$HOME/LASRecomp-Android" || exit 1
git pull --ff-only origin experimental/castlevania-belmonts-curse
pkg install -y dotnet-sdk-10.0 git python
dotnet --version

# Only download the translator and its Ryujinx dependencies, not the full repo.
if [ ! -d "$HOME/nxnative/.git" ]; then
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/seedds/nxnative "$HOME/nxnative"
fi
git -C "$HOME/nxnative" sparse-checkout set \
  dm/gfx/tools/dmsh_xlate dm/third_party/ryujinx

# The APK's exported ZIP is fed to the tool DIRECTLY (no unzip or renaming).
mkdir -p "$HOME/castlevania-ryujinx-probe"
python3 tools/castlevania_ryujinx_probe.py \
  "/storage/emulated/0/Download/Castlevania-shaders-SNXS.zip" \
  --out "$HOME/castlevania-ryujinx-probe" \
  --nxnative "$HOME/nxnative" \
  2>&1 | tee "$HOME/castlevania-ryujinx-probe/ryujinx-run.log"
\`\`\`

Change only the ZIP filename if Android saved it with a suffix, such as
\`Castlevania-shaders-SNXS (1).zip\`. This is **not** a rebuild of the
603 MB Castlevania AOT or the APK.

The Python step validates each SNXS v1 header (including length/size bounds),
extracts the original Maxwell bytecode locally into \`maxwell/*.bin\`,
and creates \`jobs.json\`, \`errors.txt\` and \`report.json\`. The report
checks the exact TEX.B opcode and handle register at the five previously
logged failure positions. These checks were performed against the user's
actual ZIP: all five matched. Their **full 16-digit names differ** between
the runtime log and the corpus; the shared initial 8 digits plus matching
PC/instruction/register, not an equal full hash, establish correspondence.

Then \`dotnet run\` builds the isolated \`dmsh_xlate\` tool from nxnative
using its vendored Ryujinx source, and attempts to generate \`spirv/*.spv\`
and reflection \`*.res.json\`. The build may download ordinary NuGet packages
once; subsequent runs reuse its \`obj/bin\` and NuGet caches.

If the phone's \`dotnet run\` fails due to Android/Termux package
compatibility, preserve \`ryujinx-run.log\` and **do not modify the functioning
Castlevania runtime**. No runtime modification happens during this probe.

## Interpreting the experiment

The \`job\` metadata intentionally contains empty \`tex\`, \`img\`,
\`attr\` and \`fout\` fact tables. Missing texture dimensions, constant
buffer 1 jump tables and resource states can cause translation failure
or inaccurate SPIR-V. Translation success here is a compatibility signal,
NOT a drop-in ScarletNX shader.

The captured five failing instructions are Maxwell TEX.B at the precise
logged PCs (304, 651, 648, 661, 720). In the last two shaders, register
R12 is copied from R4 via MOV.R immediately before TEX.B. Tracing beyond
the copy requires control-flow analysis and resource binding support.

Only if Ryujinx produces validated SPIR-V with a compatible reflection
will an opt-in Vulkan binding adapter be considered. Never load its raw
SPIR-V in the current ScarletNX Vulkan pipeline: the descriptor layouts
are different.

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
