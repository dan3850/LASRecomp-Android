# Castlevania: Ryujinx Vulkan runtime bridge — experimental trial

Date: 2026-10-22. ONLY `experimental/castlevania-belmonts-curse`.

### Why we reached this stage

The user's Termux verification printed:
- `Ran 4 tests ... OK`.
- `ScarletNX SPIR-V bridge (offline): 5 shaders`.
- `spirv-val: all five passed (Vulkan 1.3)`.

This establishes offline SPIR-V structural and Vulkan environment validation.
**It does not yet prove a correct rendered frame on Adreno.**

### What this branch now adds

1. `tools/package_castlevania_ryujinx_runtime.py` builds a private
   `.snxrbr` binary from the five original `SNXS` captured Maxwell programs
   and the user's locally validated `bridge-manifest.json` + `*.bridge.spv`.
   It verifies SHA-256, descriptor sets and supported texture-source forms;
   includes complete original Maxwell code for **byte-for-byte runtime matching**.
2. `CastlevaniaSnxBootActivity` can import that file through Android document
   picker into app-private `snx-games/0100BA4026E94000/ryujinx-bridge.snxrbr`.
   The new toggle defaults to OFF.
3. Only Castlevania's explicitly opted-in SDL process receives the
   `SNX_RYUJINX_BRIDGE` environment variable; Mario never does.
4. `patch_scarletnx_ryujinx_runtime.py` injects the standalone header into
   **only the temporary pinned ScarletNX `gpu/vk/pipeline.c`** while building.
   The wrapper's EXIT trap restores the upstream source. No AOT ABI or game
   code changes.
5. At runtime, a shader is eligible only when its entire Maxwell bytecode
   and length exactly match one of the five private captures, stage is FS,
   and the pipeline does not request integer textures/render targets,
   early-Z, unfed attributes, or a depth compare override.
   On mismatch or unsupported device capabilities, the native translator is
   used. `vkCreateShaderModule` rejection also retries the native translator.
6. The `ShaderInfo` for a matched shader is reconstructed with the
   reflected uniform buffer slots and fragment I/O location masks.
   Fragment texture descriptors use **CB2 + CB2** OR-combined live
   texture/sampler words; types are 2D, bindings are `34..97` in
   descriptor set 1. GPU texture handles are never hardcoded.
   The Ryujinx shaders were adapted offline for native resolution 1×.
7. Experimental Ryujinx SPIR-V is **not persisted** into the shared
   shader binary cache, to preserve the original translation path.

All shader bytes, assets and metadata remain local to the user's phone.
No game-derived shader or ROM data is committed to GitHub.

### First trial on Termux

The five `spirv-val` modules and original captured ZIP must still be on
the phone in the existing home/Download paths. First update:

```bash
cd "$HOME/LASRecomp-Android" || exit 1
git pull --ff-only origin experimental/castlevania-belmonts-curse

# Creates the pack from already captured files: NO AOT rebuild.
bash preparar-castlevania-ryujinx-pack-termux.sh

# Preserves previous functioning experimental APK; incremental rebuild only.
bash compilar-castlevania-ryujinx-termux.sh
```

Install the new `Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk`.
In the Castlevania launcher:
1. First leave `Ryujinx (EXPERIMENTAL): DESLIGADO` and test that the old
   runtime still boots.
2. Tap `Importar ponte Ryujinx privada (.snxrbr)`, selecting
   `Download/CastlevaniaRecomp/Castlevania-Ryujinx-Ponte.snxrbr`.
3. Turn `Ryujinx (EXPERIMENTAL)` ON and launch the **same** previously broken
   game scene. Compare image, flicker, missing geometry, shaders rejected.
4. Return to launcher, use `Salvar log` and send the text log. The log
   should show `experimental Castlevania Ryujinx bridge loaded` and any
   `Ryujinx exact Maxwell match` lines. If no match, avoid guessing: inspect
   source lengths and the runtime key states.
5. Turn OFF to revert to the original shader translator **without
   recompiling**. The original APK is preserved separately as
   `Castlevania-SNX-Runtime-ANTES-RYUJINX.apk`.

### Limitations

This is a controlled test, not yet a replacement for the ScarletNX shader
translator. Runtime pipeline creation, CB2 descriptor validity, varying I/O
and images on the Adreno still need actual game evidence. SPIR-V `spirv-val`
checks only binary validity and Vulkan environment rules. Do not install or
share the private pack except for personal testing. Shader capture may not
match if the game builds variants with different Maxwell bytecode.

Preserve the pinned ScarletNX source and never change Mario's stable branch.
