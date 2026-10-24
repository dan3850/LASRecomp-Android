# Zelda: exact reuse of resolved descriptor state

This is the next nxnative adaptation after transfers, uniform snapshots,
clear load actions and proven uniform prefixes. It accelerates the existing
descriptor-cache lookup, keeping the complete resource-resolution path.

## Audit and adaptation

Reference: [nxnative 3eb1d76](https://github.com/seedds/nxnative/tree/3eb1d76f5ddd56277f68fefbe162ec83a54899a1),
`dm/gfx/nvn/nvn_mtl.m:args_sync_dirty/encode_args_`. nxnative reuses a stage's
encoded arguments when its resource registration, dirty generations and
binding state remain valid. That broad early-return rule cannot be copied
directly here: it depends on tracking all observers and writes.

Pinned ScarletNX `34853eeae5af132e320adbb0193f13344085bf89` already:

- Caches uniform bindings and validates memory/pending GPU results.
- Reuses texture metadata, views and samplers, with resource transitions and
  feedback handling during `stage_set`.
- Reuses descriptor sets by layout plus two independent content hashes in
  `desc_set_cached`, recording allocation/updates asynchronously.
- Suppresses redundant descriptor bind commands and other dynamic state via
  `g_dyn`; pools are retained and reset only at frame-slot recycling.

Those mechanisms are preserved. The remaining repeated work selected here is
the two descriptor hashes: even a set found in the cache requires hashing
every resolved buffer/view/sampler/offset/range/layout/array entry again. Two
256-entry indexed arrays alone take 3,078 `dset_mix` calls per lookup.

`SNX_VK_BIND_REUSE=1` adds a small, exact state lookup before that original
hash cache. The initial implementation deliberately leaves `stage_set`'s
resource resolution, strict reads, uploads, storage/feedback tracking and
barriers byte-identical. Full generation-based skipping of resource-state
construction remains separate work.

## Adaptive lookup and correctness

Ten bounded entries retain the most recent state of each descriptor layout
within one frame. A complete key includes, in write order:

- Binding, descriptor type, count and destination array element.
- Every buffer handle, offset and range.
- Every image view, sampler and image layout.
- Every texel-buffer view.

The comparison excludes C padding and temporary pointer addresses. A hit
compares every included field, preserves the existing global reuse statistic
and returns the same immutable descriptor set without recalculating hashes.
Unknown types, chained extensions, ambiguous/missing pointers or oversized
keys retain the original lookup. Null resources supported by the original
path remain expressible; no new feature acceptance is introduced.

The option warms an entry only after two consecutive original lookups for
that layout/frame return the same set. Until then no complete key is built.
When inputs keep changing, it keeps the original hash lookup and avoids
repeated full key copies. A warmed comparison stops at the first mismatch,
then runs the original lookup. This controls the miss-path overhead; it does
not guarantee a speedup when few states repeat.

Entries are valid only for the original cache's monotonic frame identifier.
They never extend descriptor/resource lifetime, add a wait, reuse a reset
pool's set or retain a failed allocation. If original creation advances the
frame, the new state is not saved. Original asynchronous stand-ins and their
deep-copied descriptor packets are retained. All shader instructions, guest
writes, AOT/CPU ABI, draw counts, resolution, audio, timing and Stable60 remain.

Each key is capped at 19,064 bytes for the pinned binding limits; ten complete
entries require less than 192 KiB of bounded state. There is no per-lookup
allocation or full-size automatic key array. The relevant Vulkan rules are
[descriptor-write fields](https://docs.vulkan.org/refpages/latest/refpages/source/VkWriteDescriptorSet.html)
and [pool reset/lifetime](https://docs.vulkan.org/refpages/latest/refpages/source/vkResetDescriptorPool.html).

## Instrumentation and validation

The runtime defaults OFF. Only the new binding profile defaults **Reutilizar
bindings validados** ON, and saved preferences override that default.
`tools/patch_scarletnx_zelda_bind_reuse.py` applies after uniform-extent and
restores before it, preflighting all anchors/header before any write.
`stage_set` calls the wrapper after it has completely constructed its writes.
No shader cache key/path/format or persisted metadata is changed.

`SNX_BIND_REUSE_META_V1` reports the option, ten slots, maximum key size and
the retained resource checks. `SNX_BIND_REUSE_V1` reports lookups, fast hits,
original lookups, key refusals, bytes built during key warmup, bypassed mix
calls and warmed states. A refusal counts a rejected key-build/comparison
attempt, not all requests with an unsupported shape. A warmup copy is not an
upload. Mix calls are CPU operation counts, not GPU time, milliseconds saved
or FPS. The analyzer requires one matching summary per complete window and
still accepts old logs without these tags.

Host checks:

- All **37** performance audit tests pass, zero skips, with a real
  `spirv-val`, retaining previous shader, ownership, transfer, uniform,
  clear, extent, `/dev/full`, Bionic `O_SYNC` and byte-exact rollback checks.
- Actual `DescWrites`, original/renamed hash caches, hash mixer, descriptor
  recorder packets, deep-copy callbacks, stand-in resolver and frame resets
  are compiled with a Vulkan endpoint model. Fifty synchronous/asynchronous
  scenes replay **3,200 bindings** through old/new paths and compare every
  resolved descriptor reaching the model. This is not a GPU/pixel test.
- Coverage includes repeated and alternating layouts, more layouts than
  retained slots, two 256-entry arrays, buffer/image/sampler/layout changes,
  offsets/ranges/types/counts/array elements, write order, texel views, empty
  sets, padding/pointer changes, unsupported/chained shapes, allocation
  failure, frame changes during creation, pool recycling and stand-in index
  wrap. Caller data is overwritten before delayed recorder execution.
- Stable cases remove only the expected hash work; actual `dset_mix` call
  deltas equal the new counter exactly. Alternating changed-buffer cases
  perform no full-key copy. Allocation/bind behavior is preserved. The whole
  `stage_set` body is also checked byte-identical, retaining its resource,
  memory, upload and barrier operations.
- The same fixture passes AddressSanitizer/UndefinedBehaviorSanitizer.
  LeakSanitizer cannot inspect this host's `/proc/.../task`; this extra run
  uses `ASAN_OPTIONS=detect_leaks=0` and is not a successful leak check.
- Five full patched C units (`render.c`, `renderer.c`, `pipeline.c`,
  `record.c`, `buffer.c`) pass syntax checks with generated pinned settings
  and real Vulkan/volk/VMA headers. Shell syntax and whitespace pass.

No Java/Android APK, Vulkan driver or Zelda run is performed on this host.
Any on-device FPS gain or regression remains to be measured. Missing
shadows/light/water are unresolved and are not claimed fixed by this lookup.

## Incremental Termux build and A/B

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-bindings-termux.sh
```

Output: `/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-BINDINGS.apk`.
The wrapper tests components, reuses the existing AOT/build/shader caches,
checks all five profile assets and runtime markers in the signed APK, and
preserves `Zelda-SNX-UNIFORMES-ALCANCE.apk` plus the older variants. An existing
extent APK also gets a once-only
`Zelda-SNX-UNIFORMES-ALCANCE-ANTES-BINDINGS.apk` backup; absent APKs cannot be
backed up. FSWZADD remains OFF. Install as an update.

Keep previous options equal in both trials, capture OFF, telemetry LEVE,
native translator and the same Stable60 state. Warm the cache/route. Run
90 seconds with only **Reutilizar bindings validados** OFF; end the game
process, repeat ON with the same save, route, camera, resolution, refresh,
cooling and power conditions. Export `Zelda-Bindings-OFF.txt` and
`Zelda-Bindings-ON.txt`. No second build is needed. Check visuals/audio/speed.

```bash
python3 tools/analyze_zelda_perf.py \
  /storage/emulated/0/Download/Zelda-Bindings-OFF.txt \
  --compare /storage/emulated/0/Download/Zelda-Bindings-ON.txt \
  --skip-seconds 20 --seconds 60
```

Compare hit rate, original lookups and frame p95/p99. If few states qualify,
the added lookup overhead can outweigh the avoided hashes; repeat a promising
pair and keep OFF if worse. Current FPS streams still distinguish guest queue,
rendering and presentation enqueue, not physical scan-out or simulation FPS.
Rollback: bindings OFF and a fresh process, retaining the earlier options.
The [handoff](zelda-performance-handoff.md) maintains the full remaining port
inventory and exact continuation point.
