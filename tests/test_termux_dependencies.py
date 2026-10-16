#!/usr/bin/env python3
"""Exercise the real incremental compiler function with host C objects."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "compilar-lasrecomp-termux.sh").read_text()
COMPILE = "compile(){" + SCRIPT.split("compile(){", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


class Dependencies(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="las dependencies ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.header = self.root / "layout.h"
        self.source = self.root / "a.c"
        self.obj = self.root / "a.o"
        self.stamp = self.root / "stamp"
        self.stamp.touch()
        self.header.write_text("struct Layout { int value; };\n")
        self.source.write_text('#include "layout.h"\nint get(struct Layout *p) { return p->value; }\n')

    def compile(self, check=True):
        code = 'set -euo pipefail\nROOT="$1"; STAMP="$2"\n' + COMPILE + '\ncompile "$3" "$4" cc\n'
        return subprocess.run(["bash", "-c", code, "test", str(self.root), str(self.stamp),
                               str(self.source), str(self.obj)], capture_output=True, text=True, check=check)

    def newer_header(self, text):
        self.header.write_text(text)
        # Avoid sleeps and filesystem timestamp resolution dependencies.
        os.utime(self.obj, ns=(1_000_000_000, 1_000_000_000))

    def test_struct_change_rebuilds_reader_and_preserves_other_objects(self):
        self.compile()
        before = self.obj.read_bytes()
        self.newer_header("struct Layout { unsigned long padding; int value; };\n")
        self.compile()
        self.assertNotEqual(before, self.obj.read_bytes())
        main = self.root / "main.c"
        main.write_text('#include "layout.h"\nint get(struct Layout *);\nint main(void) {\n'
                        'struct Layout x = { .padding = 42, .value = 7 }; return get(&x) != 7; }\n')
        exe = self.root / "program"
        subprocess.run(["cc", str(main), str(self.obj), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        stamp = self.obj.stat().st_mtime_ns
        (self.root / "unrelated.h").write_text("#define OTHER 1\n")
        self.assertNotIn("CC ", self.compile().stdout)
        self.assertEqual(stamp, self.obj.stat().st_mtime_ns)

    def test_missing_depfile_rebuilds_old_cache_once(self):
        self.compile()
        Path(str(self.obj) + ".d").unlink()
        self.assertIn("CC ", self.compile().stdout)
        self.assertNotIn("CC ", self.compile().stdout)

    def test_failed_rebuild_preserves_completed_object_and_dependencies(self):
        self.compile()
        obj = self.obj.read_bytes()
        dep = Path(str(self.obj) + ".d").read_bytes()
        self.newer_header("#error incomplete header update\n")
        self.assertNotEqual(self.compile(check=False).returncode, 0)
        self.assertEqual(obj, self.obj.read_bytes())
        self.assertEqual(dep, Path(str(self.obj) + ".d").read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
