# Castlevania Vulkan / NativeAOT ABI 2 investigation

Branch: `experimental/ryujinx-runtime-nativeaot`. Baseline: `a1f8486`.
Evidence: the supplied `Castlevania-SNX-boot (11).txt` and exact sources
ScarletNX `34853eeae5af132e320adbb0193f13344085bf89`, nxnative
`1eaaab88caffcc17ada94b6dbdbe4f3b02fbb480`. No game binaries or shaders committed.

## Confirmed failures and corrections

* The supplied excerpt reports repeated `unsupported render scale pointer usage`,
  missing float32 1.0 constants, and a rejected texture descriptor. An ABI/version
  export cannot establish which C# revision produced the library. The log's older
  errors are consistent with an older adapter, but do not prove a stale library.
* The ABI 1 adapter removes `support_buffer` and rewrites its SSA pointer graph.
  Nested access chains, unused pointers and shader forms without a float-one
  literal fall outside that reconstruction. ABI 2 preserves all these instructions,
  binds the original UBO at fragment set 1 / binding 106 (`SNX_VKB_RS`), and writes
  the pinned Ryujinx std140 structure (1392 bytes, scales at offset 192).
  The native translator continues using its original 16-byte UBO at that binding;
  the selected module determines which buffer is written. No descriptor pool or
  pipeline-layout expansion is required.
* Render scale is supplied per draw: framebuffer scale and each sampled surface's
  host/guest width ratio. A submission-scoped staging allocation is reused only
  for equal contents and the same submit; no mapped pointer survives ring reuse.
* ABI 1 accepts only separate packed sampler handles and 2D textures. ABI 2
  supports combined, separate packed, separate sampler ID and constant sampler ID
  sources, with the Ryujinx-defined OR/shift operations. The metadata carries real
  2D/3D/cube, array and shadow view information. Buffer/1D/MS/descriptor arrays,
  storage buffers and storage images remain explicit native fallbacks.
* The old bridge sends empty GPU answer tables. ABI 2 queries bound CB1 data,
  actual TIC type and TIC word5 bit31 coordinate normalization synchronously on
  the GPU thread. Unknown queries fail instead of becoming invented 2D/zero data.
  Alpha-test function/reference are also queried. Every answer participates in
  cache validation, including negative answers, at both shader lookup sites.
  A changed descriptor, CB1 jump word or alpha state causes a new translation.
* Every NativeAOT build contains an exported ASCII SHA-256 identity of the staged
  accessor, adapter files and project. The runtime embeds that expected identity
  and its repository commit, and refuses a mismatch before rendering. CI builds
  both libraries afresh, checks their identities, and hashes each library again
  inside the signed APK. Only LLVM, dependency sources and compiler caches are
  reused. No previous runtime or APK is a build input.
* Persistent translated shader prewarm is bypassed only for enabled ABI 2
  sessions; existing files are preserved. The driver pipeline cache remains valid:
  Vulkan keys it using the actual shader modules and pipeline state.

## Other renderer areas inspected

Reviewed `pipeline.c`, `render.c`, `texture.c`, `surface.c`, shader metadata,
TIC/TSC resolution, framebuffer feedback copies, CB ranges, submit/staging
lifetime and the Adreno capability gate. The supplied run has zero skipped draws,
zero compute dispatches and no reported Vulkan validation errors. This does not
prove geometry, texture uploads, render-target aliasing or synchronization are
correct, and does not justify unrelated barrier/driver toggles. Existing Host1x
relocation, external RomFS and FSWZADD patches are retained in the CI runtime.
The ABI 1 exports and legacy manual native-library workflow remain available.

## CI and APK

`ScarletNX Castlevania Graphics ARM64 APK` builds and tests actual C#/NativeAOT on
Linux, validates SPIR-V with `spirv-val`, publishes Android Bionic ARM64, builds the
pinned full ScarletNX runtime with NDK r28c/LLVM 23.1.3, and packages the existing
Java launcher with the exact native SDL Java API. The new package ID ends in
`.graphics`, preserving the previous installation and its data.

CI has no private 603 MB Castlevania AOT module. The launcher therefore adds an
import button for the user's existing `0100BA4026E94000_code.so`. It copies to
private read-only storage with atomic replacement, validates ELF64/LE/AArch64
ET_DYN, and lets ScarletNX verify the module ABI. XCI, keys, captures, controls,
logs, the old packaged-module route and the previous mode switch remain.
No Termux compilation is needed. The APK does not include game data or keys.

## Validation and limits

CI gates: source identity mutation test; actual C descriptor/CB1 invalidation,
handle modes and staging lifetime tests; actual managed descriptor rewrites for
all four handle modes; preservation of non-decoration instructions; real native
synthetic Maxwell translation; SPIR-V validation; ARM64 ELF/export checks; signed
APK byte-for-byte library checks. Synthetic shaders are authored test inputs,
not captures or per-game shader replacements.

No RedMagic/Adreno execution is available in CI. Integer/unfed-varying/forced
Early-Z fragments continue to the native translator with explicit diagnostics.
Passing CI proves the tested translation, ABI, packaging and build behavior; it
cannot establish that the black scenery, purple triangles or corrupted polygons
have disappeared. No screenshots were attached in this request, only the log.

## Executed results (2026-10-22)

NativeAOT CI job: https://github.com/dan3850/LASRecomp-Android/actions/runs/39802490581
`nativeaot` succeeded: two preparation tests, two ABI-2 tests (including the
compiled C callback/staging suite), seven managed adapter cases and four actual
NativeAOT cases. Every emitted test module passed `spirv-val`. The Android ARM64
library was published successfully (9,659,568 bytes).

Host library CI: https://github.com/dan3850/LASRecomp-Android/actions/runs/39803358134
This builds the same identity `ac57e9d7e5ac10804711ba2ce58bef8cbe1e91357bef3a2b6fdff52ddb8248ed`
for private offline regression. It uploaded no user capture. Only the binaries
compiled in Actions were executed locally; no local compilation was performed.

The user's five previous Maxwell captures all passed actual ABI-2 translation,
reflection-to-metadata checks, descriptor-set/binding checks and SPIR-V validation:

| Capture prefix | Maxwell bytes | Adapted SPIR-V bytes | Textures | CBUFs |
|---|---:|---:|---:|---:|
| 214b89d4 | 6,912 | 94,384 | 8 | 5 |
| 41e4dbaf | 7,816 | 104,332 | 9 | 5 |
| 642ea78b | 5,968 | 78,692 | 9 | 5 |
| 7e305789 | 6,056 | 80,472 | 8 | 4 |
| fc2b7c81 | 16,968 | 182,760 | 12 | 4 |

These offline calls retain the earlier corpus assumptions: 2D textures,
normalized coordinates and disabled alpha test. They contain no CB1 data;
CB1 queries were configured to fail, and none of these five requested one.
Therefore this proves adaptation/translation for those inputs, not the live
TIC values, the missing sixth capture, every shader in the later log, or
correct device rendering. No captured shader bytes or generated game SPIR-V
were committed or uploaded to GitHub.
