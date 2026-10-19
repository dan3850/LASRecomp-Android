# Original Ryujinx Neo touch controls: integration contract

Base: `49a683099af0ef9a64c6399b941988b7db26b0bb`.
Branch: `android/neo-radialgamepad-original`.

## Verified upstream code
- Neo: `Sunshinin11/Ryujinx_Neo/src/KenjinxAndroid/app/src/main/java/org/kenjinx/android/GameController2.kt`.
- Original component: `Swordfish90/RadialGamePad/library/src/main/java/com/swordfish/radialgamepad/library/RadialGamePad.kt`.
- License: GPL-3.0-or-later (per source header); preserve source, notices, license and corresponding-source distribution obligations.
- Library depends on Kotlin stdlib, kotlinx-coroutines, AndroidX appcompat/core and customview.
- LASRecomp builds Java directly with javac + D8, not Gradle. An AAR alone is **not** a functional integration; transitive runtime libraries must be compiled into DEX and required Android resources must be packaged.

## Controls to port from Neo
Left: analog stick, D-pad at sector 10, minus at sector 9, L at sector 2.
Right: Nintendo A/right, X/top, Y/left, B/bottom, plus at sector 9, R at sector 3.
Neo uses 12 sectors, 200dp primary-dial limit, bottom-corner anchors and 0.5–1.5 scale.
Omit ZL/ZR, L3/R3 and right analog for this game's touch layout.
HOME must call LASRecomp settings/menu directly; do not assume ESC exits into settings.

## Integration checklist
- [x] Preserve original base on a separate branch.
- [x] Add optional AAR compile/D8 input support, without modifying normal builds.
- [ ] Obtain/pin audited original AAR and Kotlin/AndroidX/coroutines runtime dependencies.
- [ ] Compile and package all dependencies/resources; fail explicitly on missing dependencies.
- [ ] Replace Canvas view with two original RadialGamePad views and correct anchors.
- [ ] Collect events and map to SDL/JNI (stick must retain analog range).
- [ ] Connect HOME to the actual in-app settings callback.
- [ ] Verify licensing of the entire distributed application.
- [ ] Compile/sign APK in Termux and test real multitouch on device.

Do not mark this feature complete until a device test confirms inputs and menu behavior.
