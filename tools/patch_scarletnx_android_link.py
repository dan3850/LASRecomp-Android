#!/usr/bin/env python3
"""Patch only the pinned Android runtime's link and its real main() trace.

The shared Bionic import library must precede static archives. Keep upstream's
-Bsymbolic (FFmpeg tables need it), without linking another libc into this DSO.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from scarletnx_elf_audit import Elf


BEGIN = "    # BEGIN LASRECOMP_ANDROID_SHARED_LIBC\n"
END = "    # END LASRECOMP_ANDROID_SHARED_LIBC\n"
ENTRY_INCLUDE = """#ifdef __ANDROID__
#include <android/log.h>
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
#endif
"""
ENTRY_TRACE = """#ifdef __ANDROID__
    /* This marker is inside the actual ScarletNX main, after dlopen/JNI/SDL.
       Its absence must never be presented as a successful runtime boot. */
    const char* boot_trace = getenv("SNX_BOOT_TRACE");
    static const char entered[] = "SCARLETNX_MAIN_ENTERED\\n";
    __android_log_write(ANDROID_LOG_INFO, "MarioSNX", "SCARLETNX_MAIN_ENTERED");
    if (boot_trace && boot_trace[0]) {
        int boot_fd = open(boot_trace, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
        if (boot_fd >= 0) {
            (void)write(boot_fd, entered, sizeof(entered) - 1);
            (void)fsync(boot_fd);
            close(boot_fd);
        }
    }
#endif
"""


def cmake_quote(path):
    value = str(Path(path).resolve())
    if any(c in value for c in ('"', ';', '$', '\n', '\r', '\\')):
        raise ValueError("unsupported character in CMake path: " + value)
    return '"' + value + '"'


def write_changed(path, text):
    if path.read_text() != text:
        path.write_text(text)
        print("Patched:", path)
    else:
        print("Already patched:", path)


def patch(source, libc, cxx, symbol_map, evidence):
    libc_elf, cxx_elf = Elf(libc), Elf(cxx)
    for elf in (libc_elf, cxx_elf):
        if elf.kind != 3 or elf.machine != 183:
            raise ValueError("expected Android AArch64 shared library: " + str(elf.path))
    if not any(s["name"] == "getauxval" and s["section"] and s["table"] == ".dynsym"
               for s in libc_elf.symbols):
        raise ValueError("selected libc.so does not export getauxval")
    evidence.mkdir(parents=True, exist_ok=True)
    target = source / "src/nx/CMakeLists.txt"
    text = target.read_text()
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError("duplicate/incomplete Android link patch")
        first, rest = text.split(BEGIN)
        _, last = rest.split(END)
        text = first + last
    # Upgrade the previously installed export-only patch, not arbitrary flags.
    text, removed = re.subn(r'^    target_link_options\(scarletnx PRIVATE "-Wl,--version-script=[^"\n]+"\)\n',
                            '', text, flags=re.M)
    if removed > 1:
        raise ValueError("duplicate legacy version-script blocks")
    anchor = '    target_link_options(scarletnx PRIVATE -Wl,-Bsymbolic)\n'
    if text.count(anchor) != 1:
        raise ValueError("pinned Android -Bsymbolic block changed")
    options = [
        "-Wl,--push-state,--no-as-needed", str(libc.resolve()), "-Wl,--pop-state",
        "-Wl,--version-script=" + str(symbol_map.resolve()),
        "-Wl,-Map=" + str((evidence / "scarletnx.map").resolve()),
        "-Wl,--cref", "-Wl,--why-extract=" + str((evidence / "why-extract.tsv").resolve()),
        "-Wl,--trace-symbol=getauxval", "-Wl,--trace-symbol=__aarch64_have_lse_atomics",
        "-Wl,--trace-symbol=__bionic_getauxval", "-Wl,--trace-symbol=__libc_init",
    ]
    # Options contain filenames as well as flags; quote without interpreting CMake variables.
    quoted = []
    for option in options:
        if any(c in option for c in ('"', ';', '$', '\n', '\r', '\\')):
            raise ValueError("unsupported character in linker argument")
        quoted.append('        "' + option + '"')
    block = BEGIN + "    target_link_options(scarletnx PRIVATE\n" + "\n".join(quoted) + ")\n"
    block += "    set_property(TARGET scarletnx APPEND PROPERTY LINK_DEPENDS " + cmake_quote(symbol_map) + ")\n"
    block += END
    write_changed(target, text.replace(anchor, anchor + block))
    entry = source / "src/nx/runtime/entry.c"
    text = entry.read_text()
    include = '#include <string.h>\n'
    if ENTRY_INCLUDE not in text:
        if text.count(include) != 1:
            raise ValueError("pinned entry includes changed")
        text = text.replace(include, include + ENTRY_INCLUDE)
    anchor = 'int main(int argc, char** argv) {\n'
    if ENTRY_TRACE not in text:
        if text.count(anchor) != 1:
            raise ValueError("pinned main entry changed")
        text = text.replace(anchor, anchor + ENTRY_TRACE)
    write_changed(entry, text)
    metadata = dict(libc=str(libc.resolve()), cxx=str(cxx.resolve()),
                    libc_sha256=hashlib.sha256(libc_elf.data).hexdigest(),
                    cxx_sha256=hashlib.sha256(cxx_elf.data).hexdigest())
    (evidence / "selected-runtime-libraries.json").write_text(json.dumps(metadata, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--libc", type=Path, required=True)
    p.add_argument("--cxx", type=Path, required=True)
    p.add_argument("--symbol-map", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    args = p.parse_args()
    try:
        patch(args.source, args.libc, args.cxx, args.symbol_map, args.evidence)
    except (ValueError, OSError) as error:
        raise SystemExit("Android link patch refused: " + str(error))


if __name__ == "__main__":
    main()
