# Zelda: immediate full clears as Vulkan load actions

This optional adaptation continues the transfer and strict uniform work that
received positive qualitative feedback on the RedMagic 11 Pro. It replaces an
eligible new pass's `LOAD` followed by `vkCmdClearAttachments` with
`VK_ATTACHMENT_LOAD_OP_CLEAR` at that same pass's beginning. Every requested
clear still occurs. No game/AOT, shader arithmetic, resolution or timing change
is needed.

Reference: [nxnative at 3eb1d76](https://github.com/seedds/nxnative/tree/3eb1d76f5ddd56277f68fefbe162ec83a54899a1),
`dm/gfx/nvn/nvn_mtl.m`, where color/depth/stencil clear flags select Metal
attachment load actions. The Vulkan adaptation is independently implemented
against ScarletNX `34853eeae5af132e320adbb0193f13344085bf89`. It uses immediate
command order, without copying Metal code or adding nxnative's deferred-pass
or broad attachment-discard machinery.

## Eligibility and original behavior

The original `render.c:render_begin` already keeps a compatible pass open,
transitions attachments, records feedback layout state and uses `LOAD`/`STORE`.
`vk_render_clear` then records an explicit clear. Reusing an already open pass
is valuable; this change never ends one just to get a clear load action.

The independent runtime option is `SNX_VK_CLEAR_LOAD=1`, default OFF in the
runtime and ordinary audit profile. A new clear can use the load action only
when all of these conditions hold:

- A new pass is already needed by the original target/layout rules.
- There is no GPU predicate and no clear scissor, including a full-area scissor.
- The layer index is zero; all bound images have exactly one layer, equal
  nonzero render extents and no volume/3D slices.
- A requested color clear covers all four channels and names a valid bound
  slot. Unselected MRT slots keep their original `LOAD` behavior.
- A requested depth/stencil clear covers every aspect actually present in
  that attachment. Depth-only or stencil-only D24S8 clears keep the old path.
- Bound attachment image handles are distinct; duplicate slots/image aliases
  keep the old path.

The original clamped depth, stencil truncation and raw color bits are retained.
The chosen sRGB/integer attachment view is unchanged. The existing recorder
deep-copies the clear values with the rendering description. Same-pass clears,
partial masks, predicates, scissors, arrays, invalid slots and other rejected
cases use the original clear commands. The normal draw entry point passes no
clear description.

Store operations, resource visibility, barriers, feedback ordering, write
generations, full-target tracking and undefined-depth bookkeeping remain in
the original paths. There is no delayed clear, future-command lookahead,
`DONT_CARE`, skipped draw or added synchronization. The semantic basis is the
Vulkan specification's [attachment load operations](https://docs.vulkan.org/refpages/latest/refpages/source/VkRenderingAttachmentInfo.html):
`CLEAR` initializes the selected attachment aspect inside the render area at
rendering begin, using its clear value. The eligibility rules make that area
and layer match the original full clear.

This may avoid an attachment load and a separate clear command on a tile
renderer. The driver might already optimize the old command sequence. No
bandwidth, milliseconds or Android FPS gain is claimed before device trials.

## Implementation, evidence and limits

`tools/patch_scarletnx_zelda_clear_load.py` applies after the uniform patch and
restores before it. All anchors and the generated header are checked before
writing. Repeated apply/revert operations and full-stack byte restoration are
tested. The header's counters run under the renderer lock and reset per window.

`SNX_CLEAR_LOAD_META_V1` identifies the effective option and immediate,
single-layer policy. `SNX_CLEAR_LOAD_V1` reports requests, candidates,
`folded_commands`, same-pass `continued_fallbacks`, per-aspect clear counts
and initialized pixel areas. Pixel counts are not measured memory traffic;
one folded command may contain both color and depth/stencil clears. The log
analyzer requires one matching summary for each complete telemetry window,
rejects mode changes and still accepts older logs without these records.

Host validation completed:

- All **29** `test_zelda_perf*.py` tests pass with zero skips and a real
  `spirv-val`, retaining the `/dev/full` and Bionic `O_SYNC` regressions.
- The new fixture compiles the actual pinned pass begin/end, clear,
  scissor predicate, feedback, write bookkeeping and dynamic-rendering
  recorder functions. Forty scenes compare old/new pixel arrays and metadata
  in an instrumented Vulkan model. Recorder callbacks run only after stack
  clear values have been deliberately overwritten.
- Scenes include raw integer/float bits, clamped/NaN depth, truncated stencil,
  all eight MRT slots, slot holes, target switches, repeated/same-pass clears,
  GPU predicates, partial/full/Y-flipped scissors, partial masks/aspects,
  layers, unequal extents, duplicate images, feedback layouts with/without
  local reads, sRGB selection and failed attachment views. OFF and invalid
  options keep the original command counts. ON replaces only eligible clear
  commands; pass, query, profiler, barrier and other work counts match.
- Complete patched `render.c`, `renderer.c` and `record.c` pass C syntax
  checks with the real Vulkan, volk and VMA headers. Settings are generated
  from the pinned source specification. Shell syntax and whitespace pass.

The fixture is a pixel model, not a Vulkan driver/GPU test. No Android APK,
Java/Android build, game run or full AOT rebuild was performed on this host.
Missing shadows, light shafts and water effects are still unresolved. This
change is neither evidence of their cause nor a promised visual fix.

## Incremental Termux build and comparison

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-clears-termux.sh
```

Output: `/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-CLEARS.apk`.
The wrapper reuses the AOT/build caches, checks all three current profile
assets and the compiled transfer/uniform/clear markers in the signed APK,
and leaves `Zelda-SNX-UNIFORMES.apk` and `Zelda-SNX-NXNATIVE-TRANSFER.apk`
available. An existing uniform APK also gets a once-only
`Zelda-SNX-UNIFORMES-ANTES-CLEARS.apk` backup. Missing reference APKs cannot be
backed up. The new profile defaults the clear option ON; saved preferences
take precedence. FSWZADD is explicitly OFF.

Install as an update. Keep **Reutilizar buffers e agrupar transferencias**
and **Uniformes em snapshots reutilizaveis** ON, capture OFF, telemetry LEVE,
the native translator and the same Stable60 state. Only change **Limpezas
completas no inicio do passe** between trials:

1. Warm the route/cache. Start a fresh game process with clears OFF, play
   the same route for 90 seconds, export the log as `Zelda-Clears-OFF.txt`.
2. End the game process. Repeat with clears ON, same save/camera/resolution,
   display refresh, cooling and power state; export `Zelda-Clears-ON.txt`.
3. Repeat the pair if it suggests a gain. Check shadows, indoor lighting,
   water, audio and animation speed. Do not mix capture/detailed profiles
   into the LEVE comparison.

```bash
python3 tools/analyze_zelda_perf.py \
  /storage/emulated/0/Download/Zelda-Clears-OFF.txt \
  --compare /storage/emulated/0/Download/Zelda-Clears-ON.txt \
  --skip-seconds 20 --seconds 60
```

Compare frame interval p95/p99 and CPU/GPU profile evidence as well as
`folded_commands`. Zero folds means this path cannot explain any observed
gain. The current streams distinguish guest queue, rendered frames and
successful presentation enqueue; they do not measure physical scan-out or
simulation FPS. No second build is needed for OFF/ON. Roll back by turning
only the clear option OFF and starting a fresh game process; the approved
transfer/uniform options remain independent.

The full remaining inventory and exact continuation point are maintained in
[the handoff](zelda-performance-handoff.md).
