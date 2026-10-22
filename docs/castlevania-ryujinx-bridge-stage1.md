# Ryujinx → ScarletNX: first experimental SPIR-V binding bridge

Date: 2026-10-22. Branch: `experimental/castlevania-belmonts-curse`.

## What is implemented

`tools/ryujinx_spirv_bridge.py` consumes the user's **local** `Castlevania-Ryujinx-Resultado.zip`.
The binary captures, converted modules, XCI, and keys are **not committed**.

- Reads SPIR-V 1.3 and Ryujinx JSON reflection. Refuses unexpected resources, image types, descriptor mismatches, CBUF locations or unsupported uses of `support_buffer`.
- Converts fragment descriptor **set 0 → 1**, Ryujinx CBUFs to actual ScarletNX CBUF bindings `0..17` and 2D sampled textures to `SNX_VKB_TEX + slot` (bindings `34..97`).
- The five captured shaders use only member **5 / render_scale** of Ryujinx `support_buffer`. Under the explicitly experimental **native 1x** assumption, replaces those plain FP32 scale loads with the constant `1.0`; drops the now unused support resource declarations and pointer access chains. Any other field/use rejects the module.
- Drops only Float64 (no 64-bit float type used) and `SPV_EXT_fragment_shader_interlock` (no interlock instructions) declarations. Everything else remains unchanged.
- Writes the remapped SPIR-V and `bridge-manifest.json` with **full** 16-digit shader keys, SHA-256 of original and transformed binaries, exact runtime CB2 texture/sampler word indices, and CB layout. Never trusts eight-character prefixes for runtime shader identity.
- `tests/test_ryujinx_spirv_bridge.py` uses **synthetic-only** data, no extracted game shaders.
- `validar-castlevania-ryujinx-bridge-termux.sh` auto-detects the result ZIP in Downloads, runs tests, installs `spirv-tools` if absent and validates each module for Vulkan 1.3 using `spirv-val`.

## Locally exercised against five captured shaders

| SHA prefix | Texture descriptors | CBUFs | Render-scale FP32 loads replaced |
|---|---:|---:|---:|
| 214b89d4 | 8 | 5 | 3 |
| 41e4dbaf | 9 | 5 | 3 |
| 642ea78b | 9 | 5 | 3 |
| 7e305789 | 8 | 4 | 4 |
| fc2b7c81 | 12 | 4 | 2 |
| **Total** | **46** | **23** | **15** |

The local structural transformation and three tests passed. **Full SPIR-V Tools `spirv-val` and Adreno Vulkan runtime execution have NOT been performed yet**; they are separate verification steps on the phone.

## How to validate on Termux (no APK build)

```bash
cd "$HOME/LASRecomp-Android" || exit 1
git pull --ff-only origin experimental/castlevania-belmonts-curse
bash validar-castlevania-ryujinx-bridge-termux.sh
```

The script writes `$HOME/castlevania-ryujinx-bridge/bridge-validation.log`,
`bridge-manifest.json`, and five `*.bridge.spv` modules. **Do not copy these
SPIR-V files into the APK**.

## Explicit next integration tasks

1. Match a runtime shader by **full source code/hash plus current stage and key state**, not prefix. Need to account for distinct captured `h ^ mix` and runtime pipeline variants.
2. Teach a new, strictly opt-in ScarletNX shader backend to build `ShaderInfo` from the reflected cbuf and texture metadata, including `ShTex` fields `bindless=1`, `bl_cbuf=2`, `bl2=1`, `bl2_cbuf=2`, `cbuf_off=texture_word_offset`, `bl2_off=sampler_word_offset`. ScarletNX's existing `tex_handle` can then OR the **live** CB2 reads; **never** treat the reflected offsets as actual TIC/TSC IDs.
3. Confirm fragment varying location/type and UBO array layout are compatible with the native pipeline before issuing Vulkan draw calls.
4. Guard the new path with a disabled-by-default switch and a per-shader whitelist, with the original shader translator as fallback. Count how many draws are actually fixed in the same scene.
5. Keep the Mario baseline and the 603 MB AOT module unchanged throughout.

The five successful Ryujinx translations and offline remapping are encouraging but **not yet proof of a rendered frame**. Directly loading these binaries would be unsafe without the runtime layer above.
