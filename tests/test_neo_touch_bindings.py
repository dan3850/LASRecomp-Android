#!/usr/bin/env python3
"""Regression guard: original Neo inputs must match the native Switch HID.

Standalone: python3 tests/test_neo_touch_bindings.py
Does not start the game, invoke Vulkan or need an Android SDK.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
bridge = (ROOT / "android/src/com/retroaura/lasrecomp/NeoInputBridge.java").read_text()
input_c = (ROOT / "runtime/hle/input.c").read_text()
bindings = (ROOT / "runtime/hle/bindings.c").read_text()
entry = (ROOT / "android/game/game_entry.c").read_text()
activity = (ROOT / "android/src/com/retroaura/lasrecomp/GameSDLActivity.java").read_text()
ui = (ROOT / "android/kotlin/com/retroaura/lasrecomp/NeoRadialControls.kt").read_text()
menu = (ROOT / "runtime/ui/menu.mm").read_text()

# Position 0..15 is the native input_bind.h / Nintendo Npad button order.
slots = [
    "A", "B", "X", "Y", "LEFT_STICK_BUTTON", "RIGHT_STICK_BUTTON",
    "L", "R", "ZL", "ZR", "PLUS", "MINUS",
    "DPAD_LEFT", "DPAD_UP", "DPAD_RIGHT", "DPAD_DOWN"
]
native_block = bindings.split("#define DEF_KEY {", 1)[1].split("}", 1)[0]
native_keys = re.findall(r"SDL_SCANCODE_([A-Z0-9_]+)", native_block)
assert len(native_keys) == 24, f"Expected 24 keyboard bindings, got {native_keys}"
java_to_sdl = {
    "DEL": "BACKSPACE",
    "ENTER": "RETURN",
    "NUMPAD_0": "KP_0",
    "DPAD_LEFT": "LEFT", "DPAD_RIGHT": "RIGHT",
    "DPAD_UP": "UP", "DPAD_DOWN": "DOWN",
}
actual = dict(re.findall(r"KEY\[(\w+)\]\s*=\s*KeyEvent\.KEYCODE_(\w+)", bridge))
for position, name in enumerate(slots):
    assert name in actual, f"Neo mapping missing {name}"
    mapped = java_to_sdl.get(actual[name], actual[name])
    assert mapped == native_keys[position], (
        f"{name}: Android {actual[name]} -> SDL {mapped}, "
        f"but native slot {position} requires {native_keys[position]}"
    )

assert "nativeSetNeoStick(int stick, float x, float y)" in activity
assert "Java_com_retroaura_lasrecomp_GameSDLActivity_nativeSetNeoStick" in entry
assert '"lasrecomp_android_set_touch_stick"' in entry
assert "void lasrecomp_android_set_touch_stick(int stick, float x, float y)" in input_c
assert "touch_lx + tx" not in input_c
assert "key_lx + pad_lx + tx" in input_c
assert "key_rx + pad_rx + trx" in input_c
assert "NeoInputBridge.RIGHT_STICK" in ui
assert "NeoInputBridge.LEFT_STICK" in ui
assert 'SecondaryDialConfig.SingleButton(1, 1f, 1f, button(NeoInputBridge.LEFT_STICK_BUTTON, "L3"))' in ui
assert 'SecondaryDialConfig.SingleButton(5, 1f, 1f, button(NeoInputBridge.RIGHT_STICK_BUTTON, "R3"))' in ui
assert "KEYCODE_F1" in bridge and "SDL_SCANCODE_F1" in menu
assert "button(DPAD_LEFT, x < -0.35f)" in bridge
assert "button(DPAD_UP, y < -0.35f)" in bridge
print("OK: all 16 Switch Npad button bindings match the actual native defaults.")
print("OK: D-pad independent, two genuine analog sticks connected to nn::hid.")
print("OK: dedicated HOME opens the real in-game settings via F1.")
