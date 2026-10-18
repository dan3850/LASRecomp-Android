# Android PR #91 comparison — Vulkan compilation worker budget

Base: `android/native-pre-opengl` at `869c17b4eaf991f0204e942c1c5a9ca52c79f4f1`.
Experimental branch: `android/compare-pr91-worker-budget`.

The independent Android port in LASRecomp PR #91 uses three shader/pipeline workers on phones. Our existing Vulkan renderer already implements strict compute-pipeline waits and persistent startup pipeline replay; this change does **not** replace or duplicate either mechanism.

This A/B experiment changes only the worker count selected in `start_workers`:
- Android default: **3** (previously at least 4).
- Other platforms: unchanged `clamp(logical_cpus - 4, 4, 16)`.
- `LARECOMP_VK_JOBS=4`: restore four workers for a comparison on the same device.
- `LARECOMP_VK_JOBS=1..16`: request an explicit valid budget. Invalid strings use the platform default.
- The chosen worker count is recorded in the Vulkan log.

Validation: `python3 tests/test_vk_worker_budget.py`. The policy test is independent of Vulkan, the game's private library and Android hardware.

No GMEM, shader translation, replay cache, graphics algorithms, FPS pacing, Vulkan API or private game code changes. This is not a demonstrated FPS or fidelity improvement until an A/B runtime test is performed on the RedMagic Adreno device. No APK is built by this commit.
