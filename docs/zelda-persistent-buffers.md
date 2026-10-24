# Persistent vertex/index/storage buffers and write-watch evidence

Updated 2026-10-24. This continues the nxnative performance adaptations after
the user said "Vamos la" to the remaining-memory/resource work. It preserves
the shadow diagnostic and every previous performance option independently.

## Actual gap and implementation

The earlier transfer port already pools **all `vk_own_res_new` resources**,
not just one DMA call site. That path must not be implemented again. The new
gap is `buffer.c`'s `make_own`/`drop_own`: unchanged vertex/index/storage ranges
are promoted into a device buffer; invalidation or cache eviction released
that buffer, and the next promotion allocated another. Existing staging
rings, cached ranges and uniform-snapshot bypasses remain.

`tools/patch_scarletnx_zelda_vb_pool.py` installs
`tools/zelda-perf/vb_pool.h` after the passive write-watch patch. The adaptation
uses nxnative's persistent-resource/lifetime idea, not Metal's no-copy API.

- `SNX_VK_VB_POOL=1`, launcher **Reutilizar buffers persistentes**. Default ON
  only in the new buffer profile; saved preferences override that default.
  Other profiles keep the option OFF unless explicitly selected.
- Only `make_own` buffers of the exact requested size and its original fixed
  Vulkan usage are eligible. Nothing is imported from arbitrary guest memory.
- `drop_own` detaches the old cache entry immediately, as before. A separate
  host record goes through the existing `vk_defer_call` completion path. Its
  buffer is not available for reuse until the frame's existing wait/landing
  and retirement have completed. No extra submit or wait is introduced.
- Idle storage is bounded to 64 entries and **32 MiB of actual VMA allocation
  size**, with oldest-first reclamation and expiry after 300 frame IDs. One
  allocation larger than the cap is destroyed normally after completion.
  Cache statistics include idle allocations. The original memory-pressure
  reclaimer can free these completed entries before evicting live ranges.
- On failure to allocate retirement metadata, use the original deferred
  destruction. On GPU allocation failure, ON can reclaim only idle entries
  before retrying; OFF keeps the original single allocation attempt. Failure
  to get staging destroys the new/completed buffer before any GPU use.
- Every original guest read, hash, strict-read rule, staging copy, GPU copy,
  barrier and draw remains. `buf_get` is byte-identical under this patch.
  The existing transfer-result pool, uniforms and descriptor paths are not
  replaced. Pooling saves allocation/destruction work, not the data upload.

The bounded pool adds retained memory and lookup work. The actual hit rate and
frame intervals on the phone decide whether it helps this Zelda scene.

## Passive write-watch diagnosis

`tools/patch_scarletnx_zelda_ww_diag.py` installs
`tools/zelda-perf/ww_diag.h`. It changes no UAPI definitions, compile guards,
kernel requests, registrations, page protections, permissions, fallback
hashes or tracking policy. No new feature is force-enabled and no new kernel
probe is performed. There is no new user toggle for this passive evidence.

Errors record fixed metadata in 16 bounded event slots, using atomic reserve
and release/acquire publication. Recording makes no allocation, takes no lock
and performs no log/syscall. Thus even initialization evidence that precedes
telemetry survives: the renderer flushes it after telemetry initialization
and at later complete windows. Nothing logs on every texture check.

`SNX_WW_META_V1` reports which native build macros were available:
`pagemap_uapi`, `wp_async_uapi`, `user_mode_uapi`, `syscall_uapi`.
`policy_changed=0` describes this diagnostic, not successful tracking.
`SNX_WW_EVENT_V1` carries an event, numeric errno and requested/reported flags.

| Event | What it establishes / next investigation |
|---|---|
| `build_uapi_unavailable` | Existing compile guard excluded tracking; inspect the reported missing header macros before considering a compatible UAPI declaration. This does not test kernel permission. |
| `disabled_by_env` | Existing `SNX_NO_WW` presence disabled tracking, even if its string value was `0`. |
| `userfaultfd_failed` | The original syscall failed; errno identifies denial/unavailability. No permission bypass is added. |
| `api_failed` | The original UFFD API/feature negotiation failed. The minor-fault attempt can legitimately fail before the existing WP-only fallback succeeds. |
| `api_ready` | That API attempt succeeded; this alone is not successful tracking. |
| `register_failed` | Original range registration failed. |
| `pagemap_open_failed` | Original `/proc/self/pagemap` open failed; original unregister behavior remains. |
| `tracking_registered` | Initialization registered tracking and opened pagemap. Later scan/remap errors still matter. |
| `remap_failed` | A replacement mapping could not be registered; original code disables tracking. |
| `scan_failed` | Original PAGEMAP_SCAN failed; caller retains its original fallback/content checks. |

The first `0e0dfa4` RedMagic APK log now confirms all four build capabilities,
successful API negotiation, then `pagemap_open_failed` with errno 13
(`EACCES`). The original `/proc/self/pagemap` open is denied in the app's
context; the exact policy responsible is not established by this log. A
Termux process is not substituted for that context. Adding UAPI declarations
cannot fix the observed failure. Preserve the original content checks.

## Counters and comparisons

`SNX_VB_POOL_META_V1` reports mode, bounds, exact size and unchanged copies.
`SNX_VB_POOL_V1` reports requests, hits, actual VMA allocation calls/successes/
failures, releases, queued/returned resources, evictions and staging failures.
`pool_entries` and `pool_bytes` are gauges: the analyzer keeps their last
value instead of summing them. Only complete, same-mode windows count.
Write-watch capabilities/events are included separately in the analyzed log.

These are work counters, not FPS gains or milliseconds. A low/zero hit rate
can make this option unhelpful. Keep the previous APK as the comparison.

First phone evidence (`Zelda-SNX-boot (1).txt`, 20 complete windows):
10,964 requests, 7,184 pool hits, 3,780 allocation calls and zero allocation/
staging failures. This establishes real reuse, with no matched OFF run yet.
Both shader and shadow capture were enabled: translated-shader persistence
was bypassed, and three depth samples were saved. The analyzer correctly
rejects this session for FPS comparison. See the current phone-evidence
section of [`zelda-performance-handoff.md`](zelda-performance-handoff.md)
for exact hash/pipeline work counts, upload identity and remaining tasks.

## Exact Termux build and device test

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-buffers-termux.sh
```

Output: `Download/ZeldaRecomp/Zelda-SNX-BUFFERS.apk`. Install as an update;
do not uninstall the working app. The prior binding APK gets a once-only
`Zelda-SNX-BINDINGS-ANTES-BUFFERS.apk` backup. Previous shadow, extent, clear,
uniform and transfer APKs stay. Source patches restore in reverse order;
Gradle/CMake/Ninja/AOT/shader caches are reused, without `clean` or a game AOT
regeneration. FSWZADD remains OFF.

1. Set **Capturar sombras OFF**, **Capturar shaders OFF**, **Registrar FPS
   LEVE**. Use the native translator and keep every previous performance
   option, Stable60, resolution, refresh and cooling equal in both runs.
2. Set **Reutilizar buffers persistentes OFF**. Start a fresh game process,
   warm up the route, play the same 90-second route and **Salvar log** as
   `Zelda-buffers-OFF.txt`.
3. Exit normally. Set only **Reutilizar buffers persistentes ON**, start a
   fresh process and repeat the route. Export `Zelda-buffers-ON.txt`.
4. Compare game visuals/audio and matching complete windows. Send both logs;
   they also contain the write-watch diagnosis, without another probe/build.

Optional local reports, using the existing analyzer:

```bash
cd "$HOME/LASRecomp-Android"
python3 tools/analyze_zelda_perf.py /storage/emulated/0/Download/Zelda-buffers-OFF.txt
python3 tools/analyze_zelda_perf.py /storage/emulated/0/Download/Zelda-buffers-ON.txt
```

If files have different names, use their exact paths. Shadow captures remain
a separate visual experiment; the analyzer rejects those sessions for FPS.

## Host validation and stopping point

49 audit tests pass, zero skips, with a real `spirv-val` retained. The complete
stack applies twice and restores every source byte. Actual `make_own`,
`drop_own`, accounting and reclamation run with ordered simulated GPU copies,
draw-data observations and retirement. Fifty modeled scenes keep the same
150 copies/pass ends and identical observed bytes in OFF/ON; ON uses 3 VMA
allocations and 147 pool hits instead of 150 allocations in OFF. This is a
controlled host case, not an Android FPS measurement or a real GPU render.
Pending buffers are never reused, original data snapshots stay immutable
for earlier work, and cap/age/size/pressure and allocation/staging/
metadata failures are exercised. ASan/UBSan pass in OFF/ON; this host cannot
run LeakSanitizer under its `/proc` restriction.

The actual POSIX tracker is compiled before/after with older and newer UAPI
fixtures. Eighteen scenario pairs (36 executions) preserve exact mocked
syscall/ioctl traces, returned state and scanned page callbacks, including
all failure stages and the existing minor-to-WP fallback. This establishes
no tracking-policy change; it is not a successful kernel test on Android.

Three full patched C units pass syntax checks: `buffer.c`, `renderer.c` and
`plat_posix.c`. Changed activity Java parses successfully; Android type/link
validation and APK generation happen in Termux. No full game/AOT or Android
APK build, device driver run, visual correction or FPS result is claimed.

Resume with clean phone OFF/ON logs and the already saved shadow ZIP: examine
pool hits/allocation calls versus frame p95/p99. The first log establishes
pagemap-open denial, so audit a safe fallback/invalidation strategy supported
by that restriction and/or resource-generation shortcuts. Dynamic
textures, broader shader preparation, partial updates and frame pacing remain
later work. Shadow-map pixels, then lights/water, remain pending separately.
