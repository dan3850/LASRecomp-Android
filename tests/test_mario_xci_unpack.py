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
        (output / "game-base[UPD][1.2.0].nsp").write_bytes(b"patch-not-a-real-rom")
    if os.environ.get("FAKE_TWO_UPDATES"):
        (output / "game-base[UPD][1.1.0].nsp").write_bytes(b"older-patch")
    if os.environ.get("FAKE_UNRELATED"):
        (output / "another-game.nsp").write_bytes(b"not-a-real-game")
elif args[0] == "unpack":
    if os.environ.get("FAKE_REQUIRE_UPDATE"):
        assert "--update" in args, "Update argument must be forwarded to Yanu"
        patch = Path(args[args.index("--update") + 1])
        assert patch.resolve().name.endswith("[UPD][1.2.0].nsp"), patch
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
        for key in ("FAKE_MULTI", "FAKE_TWO_UPDATES", "FAKE_UNRELATED",
                    "FAKE_REQUIRE_UPDATE", "FAKE_NO_MAIN"):
            env.pop(key, None)
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
        proot = self.root / "proot-distro"
        proot.write_text(
            "#!" + sys.executable + "\n"
            + "import os, sys\n"
            + "a = sys.argv[1:]\n"
            + "os.execv(" + repr(sys.executable) + ", ["
            + repr(sys.executable) + ", " + repr(str(self.fake))
            + "] + a[a.index('--') + 2:])\n"
        )
        proot.chmod(0o755)
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

    def test_detects_base_plus_120_update_and_reuses_existing_nsps(self):
        result = self.run_tool(env_extra={
            "FAKE_MULTI": "1", "FAKE_REQUIRE_UPDATE": "1",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("game-base[UPD][1.2.0].nsp", result.stdout)
        output = self.root / "Super Mario 3D World-extraido"
        self.assertTrue((output / "exefs" / "main").exists())
        self.assertTrue((output / "_yanu_converted" / "game-base.nsp").exists())
        self.assertTrue((output / "_yanu_converted" / "game-base[UPD][1.2.0].nsp").exists())
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_fails_safely_when_more_than_one_update_matches(self):
        first = self.run_tool(env_extra={
            "FAKE_MULTI": "1", "FAKE_TWO_UPDATES": "1",
        })
        self.assertNotEqual(first.returncode, 0)
        self.assertIn("--update-nsp", first.stderr)
        self.assertEqual(self.calls(), ["convert"])
        second = self.run_tool(
            "--update-nsp", "game-base[UPD][1.2.0].nsp",
            env_extra={"FAKE_REQUIRE_UPDATE": "1"},
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_does_not_guess_between_multiple_base_games(self):
        first = self.run_tool(env_extra={"FAKE_UNRELATED": "1"})
        self.assertNotEqual(first.returncode, 0)
        self.assertIn("--base-nsp", first.stderr)
        self.assertEqual(self.calls(), ["convert"])
        second = self.run_tool("--base-nsp", "game-base.nsp")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.calls(), ["convert", "unpack"])

    def test_termux_yanu_uses_direct_proot_and_preserves_spaces(self):
        converted = self.root / "Super Mario 3D World-extraido" / "_yanu_converted"
        converted.mkdir(parents=True)
        base = converted / "Super Mario 3D World + Bowser's Fury.nsp"
        update = converted / "Super Mario 3D World + Bowser's Fury[UPD][1.2.0].nsp"
        base.write_bytes(b"test-base")
        update.write_bytes(b"test-update")
        # The installed wrapper must never run. Direct proot-distro calls
        # the inner Yanu CLI without bash -c or argument splitting.
        wrapper = self.root / "yanu"
        wrapper.write_text("#!/bin/sh\nexit 71\n")
        wrapper.chmod(0o755)
        proot = self.root / "proot-distro"
        proot.write_text(
            "#!" + sys.executable + "\n"
            + "import os, sys\n"
            + "a = sys.argv[1:]\n"
            + "assert a[:3] == ['login', 'ubuntu', '--termux-home'], a\n"
            + "assert '--' in a, a\n"
            + "os.execv(" + repr(sys.executable) + ", ["
            + repr(sys.executable) + ", " + repr(str(self.fake))
            + "] + a[a.index('--') + 2:])\n"
        )
        proot.chmod(0o755)
        env = os.environ.copy()
        env["FAKE_YANU_LOG"] = str(self.log)
        env["PATH"] = str(self.root) + os.pathsep + env.get("PATH", "")
        result = subprocess.run(
            [sys.executable, str(TOOL), str(self.xci)],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["unpack"])
        self.assertEqual(base.read_bytes(), b"test-base")
        self.assertEqual(update.read_bytes(), b"test-update")
        self.assertTrue((converted.parent / "exefs" / "main").exists())

    def test_reuses_previously_converted_base_and_update(self):
        output = self.root / "Super Mario 3D World-extraido"
        converted = output / "_yanu_converted"
        converted.mkdir(parents=True)
        (converted / "game-base.nsp").write_bytes(b"cached-base")
        (converted / "game-base[UPD][1.2.0].nsp").write_bytes(b"cached-update")
        result = self.run_tool(env_extra={"FAKE_REQUIRE_UPDATE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["unpack"])
        self.assertTrue((output / "exefs" / "main").exists())

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
