# Castlevania: second graphical repair round — sixth shader

Date: 2026-10-22. Experimental branch only.

## Grounded findings from `Castlevania-SNX-boot (2).txt`

- Snapdragon/Adreno 840 on Android 16; Vulkan 1.4.295; ScarletNX pinned to `34853ee`.
- The new runtime reports `experimental Castlevania Ryujinx bridge loaded: 5 private shaders`.
- There are **five** `Ryujinx exact Maxwell match` lines with fragment texture counts 9, 8, 8, 9 and 12. Together with the observed character reappearing, this establishes genuine runtime benefit, not merely offline SPIR-V compilation.
- At 52.15s the renderer reports 183,053 draws and **0 skipped**. By 62.19s, 467,643 draws and **0 skipped**. The remaining wrong visual appearance is not explained by skipped-draw statistics alone.
- One distinct failed shader remains at 130.11s:
  `ace294a525e1e496` stage 4, TEX.B / `untracked texture handle`, `pc=651 reg=8`. This was not among the original five captures.
- Also logged: `host1x: a submit's 42 relocations are not applied`. This warning concerns the separate video-engine submission path, not proof that this causes the character's graphical defects. Do not mix it with TEX.B without evidence.
- Capture mode was ON on the latest opt-in launch. A new export from the launcher should therefore be checked for the sixth shader before requesting a new game build.

## Changes in this round

The private pack format and app import accept **5 through 32** shaders, keeping the original five-shader pack compatible. The native ScarletNX hook uses a 32-entry upper bound and an exact, byte-for-byte Maxwell-program comparison for every new shader. Every matched shader now logs its full capture key; candidates blocked by non-default fragment state explain why native fallback was retained.

`tools/castlevania_extend_ryujinx.py`:

- Searches local exported SNXS archives for the sixth shader by the `ace294a5` prefix **and** the exact TEX.B PC 651 and source register R8.
- Combines exactly the original five validated programs plus the verified new one. Errors out if the sixth is missing or ambiguous.
- Reuses cached .NET/Ryujinx translation and generates the SPIR-V 1.3 shaders.
- Runs the existing descriptor bridge, and requires `spirv-val --target-env vulkan1.3` to succeed for **all six**.
- Makes a private new `Castlevania-Ryujinx-Ponte-6.snxrbr` file without replacing the working five-shader pack.
- Does **not** commit copyrighted shader bytes, game files or keys to GitHub.
- The Termux wrapper only rebuilds the runtime **after** all six shaders pass. It reuses the existing AOT and saves the earlier APK.

### User procedure

In the currently installed Castlevania launcher, keep `Capturar shaders` ON and tap **Exportar shaders de fragmento (.zip)**. Save the new ZIP in Android Downloads with the suggested `Castlevania-shaders-SNXS` name (Android may add `(1)`).

Then in Termux:

```bash
cd "$HOME/LASRecomp-Android" || exit 1
git pull --ff-only origin experimental/castlevania-belmonts-curse
bash avancar-castlevania-ryujinx-sexto-shader-termux.sh
```

If successful, the generated APK remains
`Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk`.
Install it, import **Castlevania-Ryujinx-Ponte-6.snxrbr** via the app's
Ryujinx import button, keep the option ON and test the same scene.
The existing five-shader pack remains at
`Castlevania-Ryujinx-Ponte.snxrbr`, and the original APK backup remains
at `Castlevania-SNX-Runtime-ANTES-RYUJINX.apk`.

If the sixth shader does not pass the Ryujinx translation/bridge validation,
the one-command script stops *before* recompilation and leaves existing APK
and shaders in place. In that case inspect
`$HOME/castlevania-ryujinx-six/six-integration.log` and report the concrete
failure rather than guessing at texture types.

## Remaining limitations

Fixing a sixth rejected shader does not guarantee perfect rendering.
Texture formats, alpha/depth rules, shader stage interface layouts, missing
support-buffer features, and host1x/video effects can cause wrong pixels even
when zero draws are skipped. A screenshot or short recording comparing the
same scene with the 5- versus 6-shader pack will help prioritize the next
specific subsystem, rather than applying speculative global workarounds.
