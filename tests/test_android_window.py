#!/usr/bin/env python3
"""Host test for the real Android acquisition helper; JNI/NDK calls are mocked.

Requires SDL3 and JDK JNI headers. Set JAVA_HOME, CC, and VULKAN_TEST_CFLAGS
for non-system paths. Does not emulate Vulkan WSI or an Android device.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
javac = shutil.which("javac")
java = Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else Path(javac).resolve().parents[1] if javac else None
if not java or not (java / "include/jni.h").is_file():
    raise SystemExit("Set JAVA_HOME to a JDK with include/jni.h")
with tempfile.TemporaryDirectory(prefix="las-android-window-") as tmp:
    out = Path(tmp)
    (out / "android").mkdir()
    # Only these NDK entry points are replaced. The helper and JNIEnv vtable
    # definitions are production code / JDK headers, not duplicated test logic.
    (out / "android/native_window_jni.h").write_text('#pragma once\n#include <jni.h>\n'
        'typedef struct ANativeWindow ANativeWindow;\n'
        'ANativeWindow *ANativeWindow_fromSurface(JNIEnv *, jobject);\n'
        'void ANativeWindow_release(ANativeWindow *);\n')
    flags = shlex.split(os.environ.get("VULKAN_TEST_CFLAGS", ""))
    sanitize = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if os.environ.get("SANITIZE") else []
    exe = out / "test"
    compiler = shlex.split(os.environ.get("CC", "cc"))
    subprocess.run([*compiler, "-std=c11", "-O1", "-g", *sanitize,
        "-D__ANDROID__", "-I" + str(out), "-I" + str(java / "include"), "-I" + str(java / "include/linux"),
        *flags, str(ROOT / "tests/android_window_test.c"), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
