# nxnative/Ryujinx compute and Vulkan cache

This is the first graphics-backend replacement slice: buffer compute can run
through nxnative's real Ryujinx translator, with its own persistent cache.
It does **not** replace the complete renderer or establish a visual fix.

## Reference

Pinned [seedds/nxnative cdd56192266f0a3ef1a6589f85575b33c44c9cac](https://github.com/seedds/nxnative/tree/cdd56192266f0a3ef1a6589f85575b33c44c9cac):

- [Graphics architecture](https://github.com/seedds/nxnative/blob/cdd56192266f0a3ef1a6589f85575b33c44c9cac/dm/gfx/README.md).
- [Maxwell to SPIR-V translator](https://github.com/seedds/nxnative/blob/cdd56192266f0a3ef1a6589f85575b33c44c9cac/dm/gfx/tools/dmsh_xlate/Program.cs).
- [Compiled-library cache](https://github.com/seedds/nxnative/blob/cdd56192266f0a3ef1a6589f85575b33c44c9cac/dm/gfx/tools/dmsh_mtlcache.py).
- [Replay and pipeline archive](https://github.com/seedds/nxnative/blob/cdd56192266f0a3ef1a6589f85575b33c44c9cac/dm/gfx/nvn/nvn_mtl.m).

The adaptation reuses Maxwell translation, reflection, immutable compile
inputs and versioned cache qualification. Metal libraries/archives cannot
be loaded by Vulkan/Adreno. New C helpers map SPIR-V to ScarletNX's Vulkan
ABI using `snx_ryu_translate_v1`, already exported by the packaged general
NativeAOT library. No new managed ABI or game AOT rebuild is required.

## Implementation

`SNX_NX_COMPUTE=1` tries nxnative/Ryujinx first for buffer compute. It supplies
real launch/shared-memory parameters and the complete available C1 segment.
ScarletNX's synthetic 80-byte compute header is removed at the ABI boundary.
C0 remains the actual driver-provided uniform; the NVN HLE reference's
synthetic driver table is never substituted for it.

Reflection maps eight uniform slots and up to sixteen storage buffers.
Ryujinx storage offsets are **words**, converted to ScarletNX's byte offsets.
Read/write masks follow reflection. Original allocations, aliases, dispatches,
barriers and guest-visible writeback stay in the existing renderer. Immutable
C1 snapshots invalidate in-memory reuse on every size/value change, including
native fallbacks, so changed constants can retry the port. Extra snapshot
storage is capped at 16 MiB; reaching it retains the original native path.

The adapter checks execution model, local size, entry point, reflected resource
count, descriptor sets/bindings and storage classes. An unused support buffer
and optional capabilities are removed only after their types/operations are
proved absent. Actual FP16/FP64, Int64, textures/images, extensions, subgroup
compute, support-buffer reads and guessed/missing facts retain native
translation. Device/module/pipeline rejection retries native too.

`SNX_NX_COMPUTE_CACHE=1` enables persistence under
`shader_cache/nxnative-compute-v1/<runtime-hash>-<translator-hash>/`.
The key covers code, launch/shared-memory parameters and full C1. Loads also
compare exact original code/C1 bytes, chain identity, metadata/payload sizes
and checksums. Invalid or partial entries compile again. Writes use a process
temporary file and rename, stopping at a conservative 64-MiB budget per chain.
Earlier caches are preserved. Vulkan's opaque driver archive gets a separate
`.nxcompute1` filename; portable SPIR-V is checked against device capabilities
on load. This is on-demand compute persistence, not full offline preparation,
predictive pipeline compilation or the complete NVN replay/resource system.

## Validation and build

69 audit tests pass, zero skips: actual patched `cs_pipe`, immutable C1,
module/pipeline failure retries, cache corruption/invalidation and exact
patch restoration. The production adapter/cache's synthetic output passes
real `spirv-val` and Vulkan compute on llvmpipe LLVM 20.1.2: 14,336 exact
list/count/tail values in seven grids. Full patched C syntax, launcher Java
parsing and builder shell syntax are checked. No Android/Adreno result or
measured FPS gain is claimed. Synthetic tests control the raw translator
boundary; they do not validate Ryujinx arithmetic for every game program.
Source/tests contain no private captures or game bytes.

```bash
cd "$HOME/LASRecomp-Android"
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-nxnative-graficos-termux.sh
```

Output: `Download/ZeldaRecomp/Zelda-SNX-NXNATIVE-COMPUTE.apk`. The wrapper
preserves the preceding isolated-depth APK once and verifies the signed
runtime/profile/translator. Existing AOT/build caches are reused. This new
profile defaults **Compute nxnative/Ryujinx (teste)** and its separate cache
to ON; other profiles keep the port OFF. Saved preferences are respected.

Compare fresh processes with Compute OFF/ON only; keep the earlier fragment
**Ryujinx Vulkan** experiment OFF, captures OFF, telemetry LEVE and the same
depth/D24/performance/Stable60 settings. Require
`SNX_NX_COMPUTE_META_V1 ready=1` and
`SNX_NX_COMPUTE_PIPELINE_V1 selected=nxnative`; a later run can show disk
`cache_hits`. Translation alone does not establish driver acceptance,
correct visible lighting or an FPS gain. OFF is the immediate rollback.

## Remaining

Validate Android selection, visual output, stability and timing. Extend
resource/features and complete vertex/fragment translation, support-buffer
and stage-interface adaptation before claiming a full shader-backend port.
Direct NVN interception/replay and Metal-to-Vulkan resource/render-pass
adaptation are still pending. The complete renderer replacement and residual
shadows, flashes, haze and light shafts are not resolved by this compute slice.
