#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "tools/extract-android-crash.py"
SPEC = importlib.util.spec_from_file_location("crash_extract", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CrashExtract(unittest.TestCase):
    def test_old_report_uses_addresses_instead_of_overwritten_pc_name(self):
        symbols = {"f_7001000000": (0x100000, 0x100), "f_7002000000": (0x200000, 0x100),
                   "f_7003000000": (0x300000, 0x100)}
        log = "host pc 100034 (f_7002000000+34)\n    host lr 200088 (f_7002000000)"
        names, _ = MODULE.crash_functions(log, symbols)
        self.assertEqual(names, {"f_7001000000", "f_7002000000"})

    def test_latest_report_and_independent_pc_lr_names(self):
        log = "host pc 100034 (f_7001000000+34)\n    host lr 200088 (f_7002000000+88)"
        names, _ = MODULE.crash_functions("host pc bad\n" + log, {})
        self.assertEqual(names, {"f_7001000000", "f_7002000000"})

    def test_extract_definition_not_prototype_or_adjacent_functions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.c").write_text("void f_7001000000(Cpu *c);\n"
                "void f_7001000000(Cpu *c) {\n    if (c) { f_7002000000(c); }\n}\n"
                "void f_7003000000(Cpu *c) {\n    return;\n}\n")
            found = MODULE.extract(root, {"f_7001000000"})
            self.assertEqual(set(found), {"f_7001000000"})
            self.assertIn("f_7002000000(c)", found["f_7001000000"][1])
            self.assertNotIn("f_7003000000", found["f_7001000000"][1])

    def test_mismatched_library_rejected(self):
        log = "host pc 100034 (f_7002000000+34)\n    host lr 200088 (f_7002000000)"
        with self.assertRaises(ValueError):
            MODULE.crash_functions(log, {})

    def test_unknown_latest_crash_does_not_reuse_an_older_report(self):
        log = "*** signal 11\nhost pc 100034 (f_7001000000+34)\n    host lr 200088 (f_7002000000+88)"
        with self.assertRaises(ValueError):
            MODULE.crash_functions(log + "\n*** signal 11\nhost pc 300000 (?+0)\n", {})

    def test_existing_zip_and_real_elf_symbols_produce_bounded_source_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "build/gamecode/main"
            source.mkdir(parents=True)
            c = source / "main_000.c"
            c.write_text("typedef struct { int value; } Cpu;\n"
                "void f_7001000000(Cpu *c) {\n    c->value += 7; c->value *= 2;\n}\n"
                "void f_7002000000(Cpu *c) {\n    f_7001000000(c); c->value += 1;\n}\n"
                "void f_7003000000(Cpu *c) {\n    c->value = 42;\n}\n")
            library = root / "test.so"
            subprocess.run(["cc", "-O0", "-fPIC", "-shared", str(c), "-o", str(library)], check=True)
            nm = shutil.which("nm")
            listing = subprocess.check_output([nm, "-S", "--defined-only", "-n", str(library)], text=True)
            symbols = {n: (int(a, 16), int(s, 16)) for a, s, n in
                re.findall(r"^([0-9a-f]+)\s+([0-9a-f]+)\s+[tT]\s+(f_[0-9a-f]+)$", listing, re.M)}
            pc = symbols["f_7001000000"][0] + 4
            lr = symbols["f_7002000000"][0] + 4
            log = f"*** signal 11 accessing 0\nhost pc {pc:x} (f_7002000000+4)\nhost lr {lr:x} (f_7002000000)\n"
            archive = root / "existing.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("session/runtime-tail.txt", log)
            output = root / "report.txt"
            subprocess.run([sys.executable, str(SCRIPT), str(archive), str(root), "--library", str(library),
                            "--nm", nm, "--output", str(output)], check=True, capture_output=True)
            text = output.read_text()
            self.assertIn("void f_7001000000(Cpu *c)", text)
            self.assertIn("void f_7002000000(Cpu *c)", text)
            self.assertNotIn("void f_7003000000(Cpu *c)", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
