# Zelda: strict immutable graphics-uniform snapshots

This optional adaptation follows the user-approved transfer revision
`9b405a615cfcad9c8c0720675ed4c0f9c3b68d63`. Keep that APK as the performance
reference. The user reported a substantial improvement from its transfer
changes; this uniform change has no on-device FPS measurement yet.

## Source finding and scope

The nxnative reference `3eb1d76f5ddd56277f68fefbe162ec83a54899a1` keeps
immutable parameter data for the draws that consume it and can defer the
actual memory updates without ending a render pass (`nvn_mtl.m`, `mtl_sub_update`,
`ubp_get`, `encode_args`). This adaptation uses ScarletNX's existing Vulkan
staging and strict checks. It does not copy Metal code or change the CPU AOT.

Pinned ScarletNX `34853eeae5af132e320adbb0193f13344085bf89` already batches
inline constant words in `maxwell3d.c:r3d_const_upload/r3d_const_flush`, keeps
per-binding snapshots in `render.c:cb_get`, and limits the uniform range to
`ShaderInfo.cbuf_max`. No duplicate implementation of those mechanisms is
needed. Its shared `buffer.c:buf_get` policy, however, promotes data that stays
identical over two checks into a dedicated device buffer. `make_own` allocates
it, stages the data, ends rendering, records a copy and inserts a barrier.
Transiently stable graphics uniforms take that path too.

`SNX_VK_UNIFORM_STREAM=1` selects a graphics-only policy for ranges <=64 KiB:

1. Retain `cb_get`'s validity checks and all pending graphics/compute result
   lookup, composition and visibility operations in `buf_get`.
2. Use strict checks; none of the sampled or delayed vertex-data checks is
   enabled. Read/hash the complete range whenever the old strict path requires
   a content check. Keep the original hash algorithm and comparisons.
3. An unchanged non-owned staging snapshot is reusable only when the existing
   entry was valid and its submission still equals `vk_submit_number()`.
   Recheck that after reading guest bytes because visibility operations can
   submit work. The existing staging API retains recorded snapshots until the
   GPU is finished; no previous draw's bytes are overwritten.
4. If a new snapshot is required, allocate it from the same staging ring used
   by the original changing-data path. Avoid promotion through `make_own` for
   this graphics-uniform request. An existing dedicated buffer shared with a
   vertex consumer is retained under its original validity rules.
5. Leave compute/storage strict reads and vertex/index reads on their original
   policy, including when they share an entry with a uniform. Oversized ranges
   also retain the old policy. Zero/unbound ranges and failures keep their
   original behavior; an unsuccessful staging allocation cannot reuse stale
   data. OFF retains the baseline allocation and reuse decisions.

Guest writes still happen immediately through `gmem_write`, with ownership
handling and write-generation notifications. This first step does not defer
guest-visible updates, introduce partial GPU-write shadows, change the draw
count, shader arithmetic, resolution, guest timing or Stable60. No Vulkan
dependency is removed: the avoided copy and its barrier disappear together
only because consumers read the immutable mapped snapshot directly.

## Measurement, risk and verification

The mode logs bounded records under `vk_lock`:

- `SNX_UNIFORM_META_V1`: enabled, strict checks, 64-KiB limit.
- `SNX_UNIFORM_V1`: requests, reused snapshots/bytes, promotion bypasses,
  staged snapshots/bytes, with the existing performance-window identifier.

All counters reset per window; the analyzer includes only complete windows
with matching metadata. Existing reports without these tags remain supported.
`promotion_bypasses` counts a policy decision, not proof that a baseline VMA
allocation would have succeeded. Neither counter is an FPS measurement.

The tradeoff is that long-static uniforms can be staged again in later
submissions instead of staying in dedicated storage. CPU-visible GPU reads
also depend on the driver's memory placement. Either can offset the removed
copies/pass interruptions; compare on the device and retain OFF if worse.
No automatic gain or 60-FPS result is asserted.

Host verification completed 25 audit tests, zero skips, with a real SPIR-V
validator. The new C fixture compiles the actual `buf_get`, `make_own`,
`guest_bytes`, `vk_hash`, ownership-list helpers, `cb_get` and exported buffer
wrappers, against instrumented memory/Vulkan endpoints. It tests:

- Byte-identical results and preceding draw snapshots after repeated updates.
- Every required strict hash checking all bytes, across epochs and submissions.
- A submission change while guest memory is read; stale snapshots are refused.
- Pending direct/composed graphics and compute results preserving their paths.
- Vertex/uniform cache sharing, unchanged compute policy, noncontiguous reads,
  temporary/staging/device-allocation failure, >64-KiB and zero ranges.
- ON/OFF/invalid values, counter reset, complete-window analysis, signed APK
  asset/revision gates and exact full source-patch restoration.

In the five-check identical-content scenario, the baseline stages three times
and records one dedicated-buffer copy/pass end; ON stages once, records no such
copy and still hashes the full uniform five times. Sizes from 16 bytes through
64 KiB are exercised. These are component work counts, not a Vulkan benchmark.
Full patched `buffer.c`, `render.c` and `renderer.c` also pass host C syntax
checks with generated pinned settings and Vulkan/volk/VMA headers. Shell syntax
and whitespace checks pass. Android compilation is left to Termux.

## Build, comparison and reversal

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-uniformes-termux.sh
```

Output: `Download/ZeldaRecomp/Zelda-SNX-UNIFORMES.apk`. The wrapper preserves
`Zelda-SNX-NXNATIVE-TRANSFER.apk` and, when it exists, saves a before-uniforms
backup once. It reuses ABI-12 Stable60 AOT, build caches and shader caches;
FSWZADD is OFF. Signed current revision, runtime markers and both profile
assets are required before declaring success. Shared ScarletNX sources are
restored on exit; the uniform patch restores before transfer and telemetry.

Install as an update. The new variant defaults **Uniformes em snapshots
reutilizaveis** ON; ordinary audit/transfer variants default it OFF. A saved
preference is respected. Keep **Reutilizar buffers e agrupar transferencias**
ON for both trials, capture OFF, telemetry LEVE, native translator, and the
same state of Stable60 and the other experimental options.

Warm the route/cache. Trial A: uniforms OFF, a fresh game process, 90 seconds,
export `Zelda-A.txt`. Trial B: uniforms ON, a fresh process, same route and
duration, export `Zelda-B.txt`. Keep save, camera, resolution, refresh, cooling
and power state equal. No second build is needed to toggle the option.

```bash
python3 tools/analyze_zelda_perf.py /storage/emulated/0/Download/Zelda-A.txt \
  --compare /storage/emulated/0/Download/Zelda-B.txt --skip-seconds 20 --seconds 60
```

Compare frame percentiles and uniform work counters; the logs distinguish
renderer/queue/presentation enqueue but still cannot measure physical display
or game simulation FPS. Check graphics, audio and animation speed. Reversal:
uniforms OFF and restart the game, retaining transfer reuse ON. The original
reference APK remains available too. Missing shadows/light/water are not
claimed fixed. Read [the continuation checkpoint](zelda-performance-handoff.md)
for the complete remaining work and where to resume.
