# Experimental PR #91 shader headstart (Android Vulkan)

Branch: `android/pr91-shader-headstart`, based on `android/pr91-upload-reuse-4way`. Main branch untouched.

Adaptation from the MIT-licensed Nycolazs/Peiikai LASRecomp implementation at commit `6b0c6ec37a755d561b5debe6b6e5fa11d869945f`: `shader_prep.c`, `shader_prep.h`, and the pipeline-variant identifiers. The repository's MIT license applies. The variant list contains **only hashes and render-state identifiers**, no shader code, ROM, Nintendo binaries, keys, or fonts.

How it works: on the first native NVN device initialization, enumerate BNSH containers in the player's RomFS assets and main NSO, matching the bundled *hashes* against shader code. On Android, use the existing read-only SAF file descriptors and manifest, with no extracted archive, image, or `romfs.bin` copy. Translate both GLSL shader stages using the current Maxwell translator, compile them through the current SPIR-V cache, construct validated Vulkan graphics/compute pipeline recipes, and supply those to the **existing** `replay_get` resource registry. Driver cache is checkpointed after the batch. Pipeline resources already produced by the replay are reused when the game later produces an identical recipe; mismatches fall back to normal first-use compilation.

The first experimental Android build processes at most **96** records to bound startup latency (other platforms default disabled). These records are sorted by hash in the imported reference list, not by scene popularity; **coverage of a specific house is not guaranteed**.

A/B and controls:
- `LARECOMP_VK_HEADSTART=0`: disable entirely; `=1` explicitly enable.
- `LARECOMP_VK_HEADSTART_LIMIT=96`: default bounded count. `=0` tries all up to 1000; use only after measuring startup duration.
- `LARECOMP_SHADER_LIST=/path/records.txt`: replace the bundled record list.
- Logs: `[shader-headstart]`, `[shader] prepared ... not found ... failed ...`, `[replay]`.

Test: `python3 tests/test_shader_headstart.py` (or `CC=clang python3 tests/test_shader_headstart.py`). This tests **record parsing**, not native pipeline creation or GPU behavior. Build and run on Adreno 840 to check compilation, startup duration, real prepared counts, graphics, frame times, and audio before merging. Failure to find shaders must never skip a draw; existing replay and demand compilation remain in place.

Native code copied/adapted under MIT (copyright 2026 Peiikai), including license text in the repository's `LICENSE`. No downloadable compiled cache is shipped. No change to guest core timing, GMEM, native frame rate, audio, or render/compute synchronization.
