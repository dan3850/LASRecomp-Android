# Zelda: nxnative comparison and first Vulkan adaptation

Reference: [seedds/nxnative at ea3ed869](https://github.com/seedds/nxnative/tree/ea3ed8690b3915b1e6ec02046f18b794ccef378e),
compared with ScarletNX `34853eeae5af132e320adbb0193f13344085bf89` and this
experimental Android branch. This is an adaptation of a range-based resource
qualification strategy, independently implemented using ScarletNX's existing
APIs. No Metal source, shader library, game binary or private capture is copied.

## What already exists, and what remains different

| Area | nxnative reference | Our existing runtime | Decision |
|---|---|---|---|
| CPU texture writes | `nvn_dirty.c` protects pool pages, records write generations, handles host pre-writes and shared pages; `nvn_dirty_since_span` keeps a range handle. | `buffer.c` already tracks generations; `plat_posix.c` uses async userfaultfd/PAGEMAP_SCAN. The RedMagic log reports no write tracking and falls back to whole-content hashes. | Do not reimplement the existing tracker. Its Android activation failure is not yet diagnosed. A full fault-based fallback also needs alias, host-write and existing GPU-trap integration. |
| Per-range qualification | `nvn_mtl.m` keeps each packaged texture's `span`, `stamp` and `seen`, avoiding a global range scan when that span is unchanged. | `texture.c:mem_hash` disables its direct read whenever **any** GPU owner exists, even outside the texture's pages. Every 4 KiB then goes through `vk_guest_peek`, staging and ownership lookups. | Adapt the local-span qualification idea to remove this avoidable fallback for CPU-readable texture ranges, while preserving all content checks. |
| Render passes and buffers | Metal encoder reuse, target/range checks, dirty argument state, buffer reuse; copy boundaries can also force a commit (`g_cut_copy`). | Vulkan already has render-pass reuse, descriptor reuse, staging rings, stable buffers, dirty generations and GPU-side copies. | Audit the remaining pass breaks rather than copying Metal commit rules, which can increase submissions. |
| Shader translation | nxnative's offline Ryujinx chain supports multiple stages and its own Metal resource layout. | The live ABI-1 adapter accepts fragment stages only and rejects SSBOs/storage images and several special states. ScarletNX itself still translates vertex/compute and all 166 supplied programs. | The bridge limitation is real; it is not proof of a missing stage in the running native backend. Completing it requires stage/resource reflection, bindings and validation. No guard is removed here. |

The Linux write-watch machinery requires both host kernel support and runtime
permission. A kernel version or the existence of fault tracking in nxnative
does not establish either for this Android APK. See the kernel's
[PAGEMAP_SCAN documentation](https://docs.kernel.org/admin-guide/mm/pagemap.html#pagemap-scan-ioctl).
No speculative UAPI enablement, root requirement, new page-fault handler or
reduced content validation is introduced in this step.

## First implementation: range-qualified texture hash reads

`tools/patch_scarletnx_zelda_hash_span.py` adds the runtime option
`SNX_VK_HASH_SPAN=1`, default OFF. The launcher exposes **Verificacao de
texturas por faixa**, gated to the audit build and the Zelda child process.
This changes how bytes reach the existing hash; it does not decide that any
bytes are clean without checking them.

When the global GPU-owner flag would otherwise force `vk_guest_peek`:

1. Ask `gmem_host` whether the complete texture range is contiguous, without
   acquiring ownership or dereferencing its bytes.
2. Run `gmem_need` for the range, retaining pending compute/graphics/release
   visibility. Re-resolve the pointer afterwards.
3. Use the actual `own_hash` to check the **rounded host pages**, including
   owners beside the requested bytes on a shared 4/16 KiB page. Any owner
   retains the original per-piece `vk_guest_peek` path and owner identities.
4. Only when no page is owned, obtain the pointer through the existing
   `gmem_ptr_untracked` CPU-readable contract. The caller holds `vk_lock`,
   which prevents new GPU owners and mapping changes during hashing.
5. Run the same `vk_hash` on the same 4 KiB pieces with the same combination,
   including the final short piece. Every call still checks the full range.

There is no new GPU readback or submission. The proven owner-free interval
has nothing for `own_acquire` to land. Noncontiguous ranges, overlapping
owners and shared-page owners keep the original path. The no-owner-global
case is also unchanged. The existing texture invalidation, generation,
upload retries, shaders, draws, barriers, guest timing and Stable60 are intact.
Hash results are identical, so existing shader/driver caches need no new
namespace or deletion. FSWZADD remains OFF by default.

The required producer-lock and public memory API contracts are unchanged.
This does not add a CPU snapshot guarantee against unrelated concurrent game
writes; the original hash has no such guarantee either.

## Verification and evidence

The tests compile the actual pinned `own.c`, `vk_guest_peek`, `vk_hash` and
both versions of `mem_hash`. A shared host mapping and its mirror represent
guest CPU memory; real `mprotect(PROT_NONE)` pages detect accidental reads of
GPU-owned storage. Tests exercise:

- Identical hashes for short/final pieces, 64 KiB and 256 KiB ranges.
- A GPU owner elsewhere: a 64 KiB CPU texture changes from 16 peek/staging
  calls to zero, while both paths still hash all 65,536 bytes.
- Every 4 KiB piece modified by the CPU, with matching changed hashes.
- Owned bytes and owners outside the bytes on the same host page, for 4 and
  simulated 16 KiB ownership pages on the host.
- Noncontiguous GPU mappings and GPU-to-CPU address rebasing.
- A pending GPU write publishing an owner during `gmem_need`, which must be
  checked afterwards and retain the fallback.
- A pending CPU-visible write before hashing, zero GPU landings, option
  parsing and counter reset.
- Full real-source patch-stack application, repeated application and exact
  restoration; bounded counter parsing, missing-window detection and
  compatibility with earlier logs.

These are correctness and work-count measurements, not Android FPS or a
claim that this removes all of the measured texture hash cost. The 1f4d2a7
phone session spent 9,652.070 ms hashing in 55.101 s (about 3.83 ms/renderer
frame), but it does not reveal how many ranges will qualify for this path.
Actual savings require the on-device counters and equivalent A/B runs.

The log includes `SNX_HASH_SPAN_META_V1` at startup and one bounded
`SNX_HASH_SPAN_V1` record per telemetry window: enabled, checks, direct_calls,
direct_bytes, owned_fallback and noncontiguous_fallback. Counters run under
`vk_lock` and reset per window. `direct_bytes` means bytes hashed directly,
not bytes skipped. The analyzer sums only complete matching windows.

The range proof itself has a cost. If most ranges fall back, this can add
overhead rather than save time; that is why it defaults OFF and the same APK
supports an immediate rollback. Host verification: all 17 audit tests pass,
including the real-source stack and the new protected-page cases. Shell
syntax and whitespace checks pass. No Android build or FPS result was
produced on this host; the earlier phone report remains unchanged after the
analyzer extension.

## Termux update, build and A/B

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 SCARLETNX_ZELDA_FSWZADD=0 bash ./compilar-zelda-fps-audit-termux.sh
```

The same APK supports both trials:
`/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-STABLE60-FPS-AUDIT.apk`.
Install as an update. AOT and build caches are reused; the current APK is
preserved by the existing baseline backup. The signed runtime must contain
`SNX_HASH_SPAN_META_V1` and the current revision, and must lack FSWZADD's
marker in the requested baseline mode. The shared ScarletNX source is
restored on exit. No full game recompile is requested.

Use capture OFF, LEVE, live Ryujinx OFF, confirmed waits OFF, Ryujinx
persistence OFF, and the same Stable60 state. Warm the route/cache first.
Keep save, camera, resolution, display refresh, cooling and power state equal.
Trial A: range option OFF, fresh game process, 90 seconds, export log.
Trial B: range option ON, fresh game process, same route/time, export log.
Repeat A/B if the first pair suggests an improvement. No second APK build is
needed to switch this option. Compare frame percentiles, texture_hash time
per frame, direct_bytes and fallback counters; watch graphics, sound and
animation speed. If few bytes qualify, this step cannot remove most hashing.

```bash
python3 tools/analyze_zelda_perf.py "/storage/emulated/0/Download/Zelda-A.txt" \
  --compare "/storage/emulated/0/Download/Zelda-B.txt" --skip-seconds 20 --seconds 60
```

Rollback: turn the range option OFF and start a fresh game process. Its
OFF path retains the earlier hashing behavior in the same APK. The remaining
fronts are Android write tracking, measured Vulkan pass/copy reduction, and
the multi-stage Ryujinx resource bridge. Missing shadows/lighting remain
unresolved and are not claimed fixed by this CPU-side memory adaptation.

## Second implementation: persistent Vulkan transfers

The supplied `1f4d2a7` phone log also records substantial GPU intervals between
render passes containing copies. For example, at 71.73 s, its 511-frame profile
reports 7.33 ms/frame of copy-containing gaps (3.93 buffer-only, 1.92 including
buffer/image transfers, 1.48 including image copies). These are measured
intervals containing operations and possible GPU idle time, not an estimate of
the time this patch can save. The session had detailed diagnostics and capture
enabled. Its FPS is not a controlled baseline for the new port.

The nxnative reference uses persistent pool buffers (`nvn_mtl.m:mtl_addr`,
`blit_raw`, `mtl_sub_copy`) and reuses completed upload staging slots. Our
`owned.c:vk_own_res_new` instead allocated a Vulkan buffer for each DMA, blit,
VIC or video result, and `vk_copy_rows` always emitted batches of 64 regions,
including fully contiguous surfaces. This adaptation implements the following
using ScarletNX's Vulkan resources and existing completion machinery:

- A bounded, exact-size pool of transfer-result buffers. A resource enters it
  only after its final ownership reference is released **and** the existing
  `vk_defer_call` frame completion runs. No live owner or in-flight buffer can
  be taken from the pool. It holds at most 128 allocations / 64 MiB, accounts
  actual VMA allocation sizes, ages idle entries out after 300 frames, and
  releases idle storage during buffer-budget reclamation or before retrying a
  failed allocation. It does not add a wait.
- A new content generation for every use, including a buffer reused at the
  same resource address. The optional `OwnHooks.identity` callback and
  `vk_guest_peek` use it for owner-based hashes. Otherwise identical pointers
  could make different GPU results appear unchanged. OFF retains the original
  pointer identity exactly. This changes internal renderer structures only,
  not the AOT's ABI 12 CPU/RtAPI contract.
- Contiguous source and destination rows coalesced into one buffer copy.
  Padded or otherwise strided copies retain their original regions. No copy
  crosses padding or a layout boundary.
- A complete pitch-linear DMA overwrite copied from its existing source
  snapshot/staging directly into its result buffer, without reading/staging
  the old destination or preparing scratch rows. Block-linear layouts,
  component remaps, fills, preserved destination components and partial-row
  spans retain the original implementation. Producer/consumer barriers,
  publication through the GMMU, unmapped destination holes and memory-write
  notifications remain in place.

`tools/patch_scarletnx_zelda_transfer.py` applies this after the audit/hash-span
patches and restores it before them, including the ownership callback.
`SNX_VK_TRANSFER_REUSE=1` selects all three transfer changes. OFF keeps the
original transfer paths in the same APK. No shader arithmetic, resolution,
draw count, CPU/GPU clock or guest timing changes; no cache is deleted.

Host verification executes the actual pinned allocation/refcount, DMA and
row-copy functions with instrumented buffer/command and completion backends.
All bytes match the old implementation for contiguous and padded rows,
snapshots, overlapping guest source/destination addresses, pending source
overlays and unmapped destination holes. A contiguous 720-row transfer changes
from 12 copy commands to 1. Complete linear DMA avoids one destination-sized
staging/read operation and scratch preparation. Tests also exercise retaining
ownership across release, delayed completion, exact-size matching, pool limits,
idle expiry, allocation/staging failure, OFF, invalid options, telemetry reset
and new owner/hash identity at the same pointer. These are correctness and
work-count results, not GPU benchmark results. The full patched C translation
units also pass syntax checks with the pinned Vulkan, volk and VMA headers.
The 21 audit tests pass; full patch-stack restoration is byte-exact.

`SNX_TRANSFER_META_V1` records the effective option and cap;
`SNX_TRANSFER_V1` records hits/misses, evictions, live pool size, row-copy calls
before/after coalescing, complete linear DMA count/bytes, and destination
staging bytes avoided. The analyzer accepts only complete matching windows,
sums operation deltas, and keeps pool entries/bytes as last-window gauges.
Pool hits and removed calls establish whether the new paths ran in the game;
they do not establish an FPS gain by themselves.

Build the transfer variant on the phone:

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-nxnative-termux.sh
```

The wrapper verifies the revision and transfer marker in the signed APK and
copies it to `Download/ZeldaRecomp/Zelda-SNX-NXNATIVE-TRANSFER.apk`.
Its `Zelda-NXNative.txt` profile defaults **Reutilizar buffers e agrupar
transferencias** to ON; a previously saved preference is respected. The
ordinary audit variant defaults it to OFF. The existing AOT, saves and shader
caches are reused. FSWZADD is explicitly OFF. No Android APK was compiled on
this host, and no new on-device FPS result or graphical correction is claimed.

Install as an update. Use capture OFF, LEVE, the native translator and the same
Stable60 state. The transfer option alone can switch ON/OFF between fresh
processes without rebuilding. The existing A/B analyzer command also reports
the new transfer counters. Missing shadows, lighting and water remain a
separate graphics issue; the multi-stage Ryujinx port and Android write-watch
activation have not been implemented by this transfer change.

## Third implementation: strict graphics-uniform snapshots

The next optional adaptation avoids promotion copies for graphics uniforms
and can reuse identical immutable staging snapshots within their original
submission, while preserving the strict content checks and pending GPU-result
paths. The approved transfer profile remains available. The new build wrapper
is `compilar-zelda-uniformes-termux.sh`; it preserves the transfer APK and
produces `Zelda-SNX-UNIFORMES.apk` with a separate runtime ON/OFF option.

See [scope, validation and comparison](zelda-uniform-snapshots.md) and the
[continuation checkpoint](zelda-performance-handoff.md). This first step does
not defer guest-visible writes or implement all of nxnative's uniform update
machinery. Device FPS validation is pending; host tests are not an FPS claim.
