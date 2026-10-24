# Zelda interaction flash: opt-in color-output probe

This is **not** a graphics fix. The supplied depth ZIP shows matching
attachment and sampled planes in three captured frames. The flash persists
with isolated D24 copies OFF, so the next unknown is where HDR color first
becomes excessive.

The existing “Capturar profundidade de luz/nevoa” switch now also arms a
bounded color probe. It reads the B10G11R11_UFLOAT_PACK32 target after three
fragment stages observed in the supplied log, in the same frame:

| Stage | Fragment shader | Role |
|---|---|---|
| 0 | `e3d1871b2f5cda65` | full-size scene output |
| 1 | `f889217164842d03` | first eligible downsample/blur output |
| 2 | `23e50e818480973c` | composition output |

The roles are inferred from target sizes, shader sequence and input bindings;
they are not proof of a complete render graph. Readback reports pixel count,
zero pixels, pixels with any channel at least 16, nonfinite channels and
maximum encoded exponent. This metric identifies a jump between stages; it
does not identify the exact visual region or prove which shader is wrong.
Different target sizes mean counts should be compared as proportions.

From 15 seconds after launch it captures at most three frames, at least
15 seconds apart. Only one output per stage per frame is captured. Each
buffer is capped at 16 MiB and the existing device allocation cap. Buffer
reads occur after ordinary frame retirement; no extra submit or wait. The
image's layout/stage/access is restored after the copy. Failed allocations or
ineligible targets retain normal drawing. The switch OFF does no new
readback, pass break or allocation. ON may add up to nine pass breaks and
disk-log work, so use LEVE telemetry and do not compare FPS from the run.

Incremental Termux build, keeping caches and the accepted APK:

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-efeitos-termux.sh
```

Install `Download/ZeldaRecomp/Zelda-SNX-EFEITOS-DEPTH-DIAG.apk` as an
update. Keep **Preservar faixa de profundidade ON**, isolated D24 in
whichever state reproduced the flash, shader/shadow capture OFF, and
**Capturar profundidade de luz/nevoa ON**. Restart the game process, enter
the telephone scene, and repeat the interaction around 15, 30 and 45 seconds
after launch. Exit normally, then export the existing effects ZIP or game
log. The rows to inspect are `SNX_COLOR_PROBE_V1` with status
`queued` and `measured`, grouped by `sample` and `frame`.
Missing stages are missing evidence, not zero brightness.

No Nintendo files, captures or game assets belong in this repository.
A host syntax/source check cannot verify Adreno execution or visual
improvement. Once the stage of the first abnormal rise is established, make
a separate default-OFF correction for that stage and compare the same save
with capture OFF.
