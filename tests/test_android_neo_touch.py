"""Static integration checks; the native analog math is tested in test_android_touch_axis.c."""
from pathlib import Path

java = Path("android/src/com/retroaura/lasrecomp/GameTouchControls.java").read_text()
bridge = Path("android/game/game_entry.c").read_text()
runtime = Path("runtime/hle/input.c").read_text()
script = Path("compilar-lasrecomp-termux.sh").read_text()

assert "LEFT_STICK=16, RIGHT_STICK=17" in java
assert "place(LEFT_STICK" in java and "place(RIGHT_STICK" in java
assert "KeyEvent.KEYCODE_DPAD_UP" in java
assert "KeyEvent.KEYCODE_F, KeyEvent.KEYCODE_NUMPAD_0" in java
assert "KeyEvent.KEYCODE_W" not in java  # D-pad and sticks must stay distinct
assert "nativeSetTouchAxes(" in java
assert "resetStick(control)" in java and "releaseAll()" in java
assert "Java_com_retroaura_lasrecomp_GameTouchControls_nativeSetTouchAxes" in bridge
assert 'dlsym(RTLD_DEFAULT, "lasrecomp_touch_axes")' in bridge
assert "void lasrecomp_touch_axes(float lx, float ly, float rx, float ry)" in runtime
for slot in ("touch_lx", "touch_ly", "touch_rx", "touch_ry"):
    assert "atomic_load(&" + slot + ")" in runtime
assert "las_touch_axis(-ly)" in runtime and "las_touch_axis(-ry)" in runtime
assert "if (!menu)" in runtime
assert "licenses/Ryujinx_Neo_Android_MIT.txt" in script
print("ANDROID_NEO_TOUCH_WIRING_PASS")
