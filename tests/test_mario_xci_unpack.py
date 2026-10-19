#!/usr/bin/env python3
"""Local no-ROM regression tests for the XCI -> Yanu -> ExeFS/RomFS helper.

Run: python3 tests/test_mario_xci_unpack.py
Only invokes a tiny fake yanu-cli written to a temporary directory.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/extrair_mario_xci.py"

FAKE_YANU = r'''from pathlib import Path
import os
import sys

args = sys.argv[1:]
output = Path(args[args.index("--outdir") + 1])
output.mkdir(parents=True, exist_ok=True)
with Path(os.environ["FAKE_YANU_LOG"]).open("a") as file:
    file.write(args[0] + "\n")
if args[0] == "convert":
    (output / "game-base.nsp").write_bytes(b"converted-not-a-real-rom")
    if os.environ.get("FAKE_MULTI"):
        (output / "game-update.nsp").write_bytes(b"update-not-a-real-rom")
elif args[0] == "unpack":
    (output / "exefs").mkdir(exist_ok=True)
    (output / "romfs").mkdir(exist_ok=True)
    if not os.environ.get("FAKE_NO_MAIN"):
        (output / "exefs" / "main").write_bytes(b"fake-test-executable")
    (output / "romfs" / "asset").write_bytes(b"fake-test-data")
else:
    raise SystemExit("unexpected command " + str(args))
'''


class TestYanuXciExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.xci = self.root / "Super Mario 3D World.xci"
        self.xci.write_bytes(b"test-file-does-not-contain-a-real-game")
        self.fake = self.root / "yanu-cli"
        self.fake.write_text("#!" + sys.executable + "\n" + FAKE_YANU)
        self.fake.chmod(0o755)
        self.log = self.root / "calls.txt"

    def run_tool(self, *args, env_extra=None):
        env = os.environ.copy()
        env["FAKE_YANU_LOG"] = str(self.log)
        env.pop("FAKE_MULTI", None)
        env.pop("FAKE_NO_MAIN", None)
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(TOOL), str(self.xci),
             "--yanu-cli", str(self.fake), *args],
            capture_output=True, text=True, env=env, check=False,
        )

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_extracts_and_never_modifies_the_original(self):
        original = self.xci.read_bytes()
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / "Super Mario 3D World-extraido"
        self.assertTrue((output / "exefs" / "main").is_file())
        self.assertTrue((output / "romfs" / "asset").is_file())
        self.assertTrue((output / "_yanu_converted" / "game-base.nsp").exists())
        self.assertEqual(self.xci.read_bytes(), original)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_current_termux_command_yanu_is_autodetected(self):
        # Current Yanu bootstrap explicitly replaced yanu-cli with yanu.
        current = self.root / "yanu"
        current.write_text("#!" + sys.executable + "\n" + FAKE_YANU)
        current.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(self.root) + os.pathsep + env.get("PATH", "")
        env["FAKE_YANU_LOG"] = str(self.log)
        result = subprocess.run(
            [sys.executable, str(TOOL), str(self.xci)],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_explicit_existing_yanu_cli_remains_supported(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_second_invocation_does_not_convert_again(self):
        self.assertEqual(self.run_tool().returncode, 0)
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_multiple_nsps_require_explicit_base_choice(self):
        first = self.run_tool(env_extra={"FAKE_MULTI": "1"})
        self.assertNotEqual(first.returncode, 0)
        self.assertIn("--base-nsp", first.stderr)
        self.assertEqual(self.calls(), ["convert"])
        second = self.run_tool("--base-nsp", "game-base.nsp")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_partial_extraction_is_not_overwritten(self):
        first = self.run_tool(env_extra={"FAKE_NO_MAIN": "1"})
        self.assertNotEqual(first.returncode, 0)
        self.assertTrue(self.xci.exists())
        second = self.run_tool()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("parcial", second.stderr)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_only_selected_intermediate_can_be_deleted(self):
        result = self.run_tool("--delete-intermediate")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / "Super Mario 3D World-extraido"
        self.assertTrue((output / "exefs" / "main").exists())
        self.assertFalse((output / "_yanu_converted" / "game-base.nsp").exists())
        self.assertTrue(self.xci.exists())

    def test_rejects_bad_extension_before_invoking_yanu(self):
        source = self.root / "game.xcz"
        source.write_bytes(b"not-xci")
        result = subprocess.run(
            [sys.executable, str(TOOL), str(source),
             "--yanu-cli", str(self.fake)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
