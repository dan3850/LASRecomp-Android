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

Safety update after the user reported that the game does not open with
effect capture ON: the HDR probe now waits at least 30 seconds and 180
presented frames before its first GPU readback. It captures stages 0, 1 and
2 in *separate presented frames*, sequentially, with only one GPU buffer
pending. It cannot run while a paired depth readback is pending; depth
capture also waits for the color buffer to retire. Each output is at most
16 MiB and respects the device allocation cap. The capture retains the
existing ordered recorder, image-layout restoration and normal frame
retirement callback, with no new explicit submit/wait. The OFF path does
nothing. Because the stages no longer come from the same frame, compare
their statistics only as provisional evidence, not proof of a specific
producer. This change is a conservative boot-risk mitigation, not a
confirmed fix for the reported failure or a graphics repair.

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
the telephone scene, and keep the telephone/NPC interaction on screen around 30 seconds
and while the three serialized stages are collected. Exit normally, then export the existing effects ZIP or game
log. The rows to inspect are `SNX_COLOR_PROBE_V1` with status
`queued` and `measured`, grouped by `sample` and `frame`.
Missing stages are missing evidence, not zero brightness.

No Nintendo files, captures or game assets belong in this repository.
A host syntax/source check cannot verify Adreno execution or visual
improvement. Once the stage of the first abnormal rise is established, make
a separate default-OFF correction for that stage and compare the same save
with capture OFF.
