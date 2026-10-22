# Castlevania: result of Ryujinx SPIR-V probe and ScarletNX Vulkan integration audit

2026-10-22. Source: the user's local `Castlevania-Ryujinx-Resultado.zip`, analyzed
offline. **No captured game binaries, XCI, keys or SPIR-V were committed.**
All five shaders came from a ScarletNX `.snxs` fragment corpus
with confirmed TEX.B PC and handle register matching the runtime log.

## Confirmed translation result

The Ryujinx translator in `seedds/nxnative` returned
`translated: 5 ok, 0 failed`. There are five SPIR-V 1.3 binaries,
five reflection JSONs, and no errors in `errors.txt`.

| Prefix | SPIR-V bytes | 2D texture bindings | Uniform buffers | TEX.B PC/handle register |
|---|---:|---:|---:|---|
| 642ea78b | 78,748 | 9 | 5 | 304 / R22 |
| 214b89d4 | 94,440 | 8 | 5 | 651 / R4 |
| 7e305789 | 80,528 | 8 | 4 | 648 / R16 |
| 41e4dbaf | 104,388 | 9 | 5 | 661 / R12 |
| fc2b7c81 | 182,816 | 12 | 4 | 720 / R12 |

**46 texture declarations**, **21 unique packed texture/sampler pairs**,
**23 uniform buffer bindings**. Every image format in the reflection is
`Unknown`, and all 46 texture `type` values equal `3`,
which maps to `SamplerType.Texture2D` in the vendored Ryujinx source.
There are no storage buffers or storage images reflected.

## Exact bindless descriptor interpretation

Every reflected texture uses `cbuf_slot = 196610 = 0x30002`.
By Ryujinx's `TextureHandle.UnpackSlots`, this means both texture
and sampler handle words are read from **constant buffer 2**.

Every reflected `handle` has top nibble `1`, that is
`TextureHandleType.SeparateSamplerHandle`: handle0 and handle1
come from *separate* constant buffer words, and their resolved
20-bit texture ID / 12-bit sampler ID are OR-combined at runtime.

For example, reflected handle `0x1058005e` means:
- cbuf2 texture word offset `0x5e` = 94 words = 376 bytes
- cbuf2 sampler word offset `0x160` = 352 words = 1408 bytes
- read the **runtime words**, OR them, resolve descriptor pools.
Do not mistake the packed offset (`0x1058005e`) for the GPU texture ID
or hardcode a fixed Vulkan image.

Other examples: `0x10590062` = CB2 words 98 and 356, and
`0x1056805a` = CB2 words 90 and 346. These are shared across
several of the five shaders.

## Why the SPIR-V cannot be injected as-is

1. **Vulkan descriptor set mismatch:** every Ryujinx resource is
   decorated with descriptor `set = 0`. ScarletNX's
   `shader_vk_set(ST_FS)` returns **1**. ScarletNX fragment textures
   occupy `SNX_VKB_TEX + slot = 34 + slot`, and uniform buffers
   occupy slots 0–17, **not** Ryujinx's sequential shader bindings.
2. **Ryujinx `support_buffer`:** every generated module includes a
   `support_buffer` at `set=0,binding=0`. ScarletNX's existing
   fixed descriptor layout does not have a matching allocation or
   data writer. Each shader actually dereferences this resource via SPIR-V\n   access chains (3, 3, 3, 4, and 2 direct chains, respectively, in the\n   table order above), so merely ignoring the declaration is unsafe. It\n   cannot be satisfied with a null descriptor.
3. **GPU capabilities:** all five SPIR-V files declare
   `OpCapability Float64`, but contain **no** `OpTypeFloat 64`.
   All five declare `SPV_EXT_fragment_shader_interlock` /
   capability 5378, but have no `OpBeginInvocationInterlockEXT`
   or `OpEndInvocationInterlockEXT`. These appear to be
   *unneeded declarations*; dropping them might be valid after
   proper usage and `spirv-val` checks, but do not assume the
   Adreno driver supports them.
4. **Incomplete GPU facts:** the offline job supplied empty
   texture/image/vertex/output query tables and no runtime
   `c1` jump data. Successfully emitting SPIR-V does **not**
   establish identical rendering behavior, correct sampler types
   in all circumstances, nor accurate render-target state.
5. **Cache identity:** the captured corpus names and the runtime
   shader hash share prefixes but not complete 64-bit values.
   Matching SPIR-V to a draw requires the program code hash,
   shader stage, key state, and applicable constant-buffer reads,
   not an eight-character prefix match.

## Recommended implementation path

- **Phase A (offline; no APK build):** validate each module with
  `spirv-val --target-env vulkan1.3`, inspect actual declarations
  and usage; remove any unneeded unsupported capabilities
  only through a verified SPIR-V transformation. Confirm stable
  texture/sampler pairs and their byte offsets (above).
- **Phase B (isolated runtime feature flag):** introduce a shader
  backend interface at `vk_translate_spirv` with ScarletNX's
  native translator as default. For a known, proven fallback
  shader only, resolve the game-time program identity and load
  Ryujinx SPIR-V+reflection. Translate every descriptor set,
  uniform slot, combined sampled image and support-buffer field
  into the Vulkan data that the existing draw code actually binds.
  Avoid guest-memory reads in unsafe contexts and verify the
  sample type against descriptor metadata. Do **not** map all
  unknown shaders onto the five captures.
- **Phase C (test and compare):** run the same Castlevania scene,
  check `VK_ERROR_*` and validation warnings, count shader
  translation failures and skipped draws **per shader**, check
  textures and HDR/alpha results, and compare performance.
  Preserve Mario's known-good runtime, the current Castlevania
  APK and the unmodified 603 MB AOT.

The separate Ryujinx translation is a real success, but it is
**not a drop-in shader-backend replacement**. If descriptor mapping
proves too invasive, transplant the proven SSA handle provenance
rules into ScarletNX's native translator instead.

## Remaining known gap

The later log also contains a sixth `untracked texture handle`
shader `ace294a525e1e496`, not included in the five-shader ZIP.
Avoid claiming full Castlevania graphics compatibility even if
the first five eventually render.

Upstream code used:
- https://github.com/seedds/nxnative/blob/main/dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/TextureHandle.cs
- https://github.com/seedds/nxnative/blob/main/dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/SamplerType.cs
- https://github.com/scarletnx/ScarletNX/blob/34853eeae5af132e320adbb0193f13344085bf89/src/nx/gpu/shader/shader.c
- https://github.com/scarletnx/ScarletNX/blob/34853eeae5af132e320adbb0193f13344085bf89/src/nx/gpu/vk/pipeline.c
