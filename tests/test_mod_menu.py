#!/usr/bin/env python3
"""Real Java import/state code and real C selection hook, without Android hardware."""
import ctypes
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
javac = os.environ.get("JAVAC", shutil.which("javac"))
java = os.environ.get("JAVA", shutil.which("java"))
if not javac or not java:
    raise SystemExit("Set JAVAC/JAVA to existing JDK executables")

with tempfile.TemporaryDirectory(prefix="las-mod-menu-") as temporary:
    folder = Path(temporary)
    subprocess.run([javac, "-source", "8", "-target", "8", "-d", str(folder),
        str(ROOT / "android/src/com/retroaura/lasrecomp/Stable60Patch.java"),
        str(ROOT / "tests/Stable60PatchTest.java")], check=True)
    subprocess.run([java, "-cp", str(folder), "com.retroaura.lasrecomp.Stable60PatchTest", str(folder)], check=True)

    harness = folder / "hook.c"
    harness.write_text('#include "' + str(ROOT / "runtime/mods.c") + '"\nvoid test_reset(void) { mods_reset(); }\n')
    library = folder / "hook.so"
    subprocess.run([*shlex.split(os.environ.get("CC", "clang")), "-std=gnu11", "-shared", "-fPIC", "-O1",
                    str(harness), "-o", str(library)], check=True)
    hook = ctypes.CDLL(str(library))
    hook.rt_mod_nop.argtypes = [ctypes.c_uint64]
    hook.rt_mod_nop.restype = ctypes.c_int
    os.environ["LARECOMP_DATA_ROOT"] = str(folder)
    marker = folder / "mods/stable60-v2.enabled"
    # Java ended with the marker disabled. C must observe the SAME persisted state.
    assert hook.rt_mod_nop(0x7001019608) == 0
    marker.write_text("AE16F71E002AF8CB059A9A74C4D90F34BA984892\n")
    assert hook.rt_mod_nop(0x7001019608) == 0  # selection takes effect on restart/reset
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 1
    assert hook.rt_mod_nop(0x7001019628) == 1
    assert hook.rt_mod_nop(0x700101962c) == 0
    marker.write_text("disabled\n")
    assert hook.rt_mod_nop(0x7001019628) == 1  # no file reads on the warm path
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 0
    marker.write_text("0000000000000000000000000000000000000000\n")
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 0
    marker.write_bytes(b"x" * 97)
    hook.test_reset()
    assert hook.rt_mod_nop(0x7001019608) == 0
    print("Native mod selection: both sites, disabled/default/invalid states, cached reads and reset PASS")

    jdk = Path(os.environ.get("JAVA_HOME", Path(java).resolve().parents[1]))
    jni_test = folder / "mod-library-test"
    subprocess.run([*shlex.split(os.environ.get("CC", "clang")), "-std=gnu11", "-O1",
                    "-I" + str(jdk / "include"), "-I" + str(jdk / "include/linux"),
                    str(ROOT / "tests/mod_library_test.c"), "-o", str(jni_test)], check=True)
    subprocess.run([str(jni_test), str(folder / "private-game.so")], check=True)
