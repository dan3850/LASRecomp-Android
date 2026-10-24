# Zelda: proven uniform prefixes from cached SPIR-V

This continues the nxnative adaptations after transfers, immutable uniform
snapshots and full-clear load actions. The user reported improvements so far
and requested continuing ports from that project, rather than replacing this
runtime or restarting the audit.

## Source finding and selected adaptation

Reference: [nxnative 3eb1d76](https://github.com/seedds/nxnative/tree/3eb1d76f5ddd56277f68fefbe162ec83a54899a1),
`dm/gfx/tools/cb_extent.py` and `dm/gfx/nvn/nvn_mtl.m:ubp_get/mtl_sub_update`.
nxnative proves how far a shader reads a uniform binding so its partial-write
shadows copy only the prefix it can use. Its broader deferred GPU-update
machinery also tracks copy/storage/CPU observers and in-flight generations.

ScarletNX `34853eeae5af132e320adbb0193f13344085bf89` already batches inline
uniform words in `r3d_const_upload/r3d_const_flush`, publishes them immediately
through `gmem_write`, caches bindings in `cb_get` and limits ranges using
`ShaderInfo.cbuf_max`. The approved snapshot adaptation already avoids
promotion copies that would end passes. Adding Metal-style deferred copies
at this layer would duplicate work that is not present in the same form.
Full deferred GPU updates remain separate, unimplemented work.

There is a concrete remaining extent gap: graphics `O_LDC` instructions always
set `cbuf_max[bank] = 65536`, even when their address is fixed (RZ plus a known
offset). The translated SPIR-V still expresses that fixed address. This step
adapts the proven-prefix idea to that immutable SPIR-V. No Metal/MSL code,
private captures, game binary or shader-library asset is copied.

## Proof and fallback policy

`SNX_VK_UB_EXTENT=1` enables the independent option **Alcance comprovado dos
uniformes**. The runtime and ordinary profiles default it OFF. Only the new
extent profile defaults it ON; saved preferences are respected.

The proof accepts a deliberately narrow layout: one Uniform block containing
one 4096-element array of four 32-bit scalar components, offset zero and stride
16, with an explicit stage descriptor set and binding 0..17. Every read must
use a direct scalar access chain with exact constant member/array/component
indices. Small exact 32-bit SSA expressions (add/subtract/multiply, shifts,
bitwise operations, integer copies/bitcasts) can supply those constants.
Arithmetic retains its 32-bit wrapping semantics.

Every use of each accepted root/derived pointer is audited across the module.
Dynamic indices, loads from registers, specialization constants, pointer
escapes/copies/phis, vector/whole-block loads, unsupported chains/layouts,
duplicate bindings and grouped decorations prevent reducing the affected bank
or the whole analysis. Unknown opcode operands are treated conservatively;
an integer literal coinciding with a pointer ID may also refuse the proof.
No control-flow path is omitted, even if it looks unreachable.

The result is the greatest read endpoint rounded up to 16 bytes. Zero means
unproven: keep the existing range. A proven prefix can only reduce the final
range already constrained by the guest binding, original `cbuf_max`, alignment
and device limit. All existing strict content checks, ownership/visibility,
pending GPU-result paths and immutable snapshot lifetime rules operate on the
complete selected range. Guest writes and all shader instructions remain
unchanged. Compute keeps its original policy.

The parser caps modules at 1,048,576 words and 65,536 IDs. Invalid framing or
allocation failure retains the original range. It is a bounded proof helper,
not a replacement SPIR-V validator. The original module feature checks and
Vulkan creation remain in place. The applicable rules are specified in
[SPIR-V memory instructions](https://registry.khronos.org/SPIR-V/specs/unified1/SPIRV.html)
and [Vulkan descriptor ranges](https://docs.vulkan.org/refpages/latest/refpages/source/VkDescriptorBufferInfo.html).

## Caches, integration and counters

`tools/patch_scarletnx_zelda_ub_extent.py` applies after clear-load and restores
before it, with a full preflight before writes and exact source restoration.
The generated `snx_ub_extent.h` is included by `pipeline.c`. The proof runs
once on successful newly translated modules and on the actual persistent
cache loader's SPIR-V, skipping compute and modules whose used uniform banks
already have smaller native extents.

Proofs live in a transient `VkSh.snx_ub_extent[18]`. `ShaderInfo`, `PfShader`,
the SPIR-V words, cache format/path/key and recorded shader metadata are not
changed. No cache deletion, isolated namespace or forced shader retranslation
is introduced. ON/OFF in one APK uses the same persistence rules. Existing
build/device compatibility checks still apply across runtime revisions.
No CPU/AOT ABI change or whole-game rebuild is needed.

`SNX_UB_EXTENT_META_V1` identifies the option and proof policy.
`SNX_UB_EXTENT_V1` counts bindings, reduced bindings, requested bytes before
the new proof and selected bound bytes afterwards. They are sums of binding
ranges, not uploads or measured bandwidth savings: repeated unchanged
bindings may already reuse snapshots. Compare the existing uniform staging
counters, frame interval percentiles and profiler evidence as well. The
analyzer requires matching complete windows and retains older log support.

If few bindings qualify, the option cannot save much and adds analysis and
counter overhead. It does not add interval analysis for dynamic indices or
complete nxnative's deferred/partial GPU-write shadows. No Android FPS or
shadow/light/water correction is claimed.

## Host validation

- All **33** performance audit tests pass, zero skips, with a real
  `spirv-val`, including the existing shader, ownership, transfer, uniform,
  clear-load, `/dev/full`, Bionic `O_SYNC` and full-stack restoration tests.
- The new fixture translates **61 synthetic Maxwell programs** through the
  actual pinned decoder/translator/emitter, checking six LDC sizes, fixed and
  dynamic addresses, multiple reads and signed-offset fallback. The 54
  fixed-address modules are validated with `spirv-val --target-env vulkan1.3`.
- Input SPIR-V is byte-identical after analysis and disk reopen. The actual
  patched `pf_load_shader`, actual `VkSh`/`PfShader`/constant-read structures
  and module-creation failure path are exercised. Saved records and original
  `ShaderInfo` are unchanged. Already bounded banks and compute do not gain
  transient proofs.
- Actual binding-size code, `cb_get`, strict `buf_get`, hashes and the earlier
  snapshot implementation exercise partial updates. Every selected byte is
  checked, earlier draw snapshots remain immutable, and prior transfer/
  uniform behavior is retained. For a fixed LDC reading the first word, the
  fixture's binding/staging/hash range changes from 64 KiB to 16 bytes;
  this is a component work count, not a phone speedup.
- Allocation failure, unsupported layouts/uses, pointer escape, wrong set,
  truncated framing and 512 deterministic corrupt-word mutations are checked.
  The same native/shadow/cache/corrupt-input fixture also passes host AddressSanitizer
  and UndefinedBehaviorSanitizer. LeakSanitizer could not inspect `/proc/.../task`
  in this environment, so that extra run used `ASAN_OPTIONS=detect_leaks=0`;
  it is not evidence of a successful leak check. Runtime checks are unchanged.
- Four full patched C units (`pipeline.c`, `render.c`, `renderer.c`,
  `buffer.c`) pass syntax checks with generated pinned settings and real
  Vulkan/volk/VMA headers; `_GNU_SOURCE` is needed for the pre-existing glibc
  `Dl_info` use. Shell syntax and whitespace are checked.

No Java/Android APK, Vulkan driver execution or Zelda run is performed on this
host. The user compiles in Termux and measures on the RedMagic 11 Pro.

## Incremental Termux build and A/B

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-uniformes-alcance-termux.sh
```

Output: `/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-UNIFORMES-ALCANCE.apk`.
The wrapper runs the host-compatible component tests on Termux, reuses AOT,
CMake/Ninja/Gradle and shader caches, verifies four current profile assets and
all compiled runtime markers in the signed APK, and preserves
`Zelda-SNX-CLEARS.apk`, the uniform and transfer APKs. An existing clear APK
gets a once-only `Zelda-SNX-CLEARS-ANTES-ALCANCE.apk` backup. Missing APKs
cannot be backed up. FSWZADD stays OFF.

Install as an update. Keep transfers/uniform snapshots ON, clears in the same
state in both trials, capture OFF, telemetry LEVE, native translator and the
same Stable60 state. Warm the route/cache, then run 90 seconds with only
**Alcance comprovado dos uniformes** OFF; end the game process, repeat ON with
the same save/camera/resolution/refresh/cooling/power conditions. Export logs
as `Zelda-Alcance-OFF.txt` and `Zelda-Alcance-ON.txt`. Repeat a promising pair
and check graphics, audio and animation speed. No second build is required.

```bash
python3 tools/analyze_zelda_perf.py \
  /storage/emulated/0/Download/Zelda-Alcance-OFF.txt \
  --compare /storage/emulated/0/Download/Zelda-Alcance-ON.txt \
  --skip-seconds 20 --seconds 60
```

Rollback: extent option OFF and a fresh game process. The earlier transfer,
uniform and clear options remain independent. Actual scan-out and game
simulation FPS still cannot be inferred from the current telemetry streams.
The [handoff](zelda-performance-handoff.md) records all remaining ports and
the exact continuation point.
