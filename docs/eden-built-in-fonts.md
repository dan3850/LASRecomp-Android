# Eden-style built-in fonts for LASRecomp Android

This experimental build packages **emulator-synthesized** Standard and Nintendo Extension
TrueType fonts from Eden instead of requiring any font import from the user. These are
NOT console font dumps. On Android, `GameSDLActivity` copies them out of APK assets on
startup; `runtime/hle/pl.c` supplies them through the existing `nn::pl` HLE calls.
Any valid user-supplied system font still overrides the built-in substitute.

Upstream: [eden-emulator/mirror](https://github.com/eden-emulator/mirror),
at revision `d8c6c59b679867d2595fdc0953df033475e23380`.

Source data:

- `src/core/file_sys/system_archive/data/font_standard.cpp`
- `src/core/file_sys/system_archive/data/font_nintendo_extended.cpp`

The generated `.ttf` bytes are extracted from upstream C++ arrays with
`tools/eden-builtin-fonts.py` during CI and packaged into the APK. No download
or font import is needed on the Android device.

**Licensing:** The upstream font data is marked
`SPDX-License-Identifier: GPL-2.0-or-later` (Copyright 2019 yuzu Emulator
Project). Those files are **not** covered by LASRecomp's MIT license. The
GPL's source, copyright notice, and license distribution obligations also
apply when distributing a free APK; noncommercial use does not waive them.
Keep the source revision and full license available with distributed builds.
The APK packages the GPL-2.0 license text and an upstream source notice.
Review compatibility before using these assets in a proprietary release.

**Installation:** The experimental artifact is
`LASRecomp-Android-Fontes-Eden-Paralelo.apk`, package
`com.retroaura.lasrecomp.bootdiag.fonts`. It installs beside older
`.bootdiag` and `.bootdiag.controls` packages, because test builds signed
with ephemeral CI keys cannot reliably upgrade one another. The apps do
not share imported game files. Re-import game data in the Fonts app if needed.

**Not addressed:** Colors, NVN/Vulkan rendering issues, surface loss,
or text draw-call correctness. A valid loaded TTF does not itself prove
that the text renderer is correct.
