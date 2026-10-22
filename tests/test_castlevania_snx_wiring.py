#!/usr/bin/env python3
"""Static integration guards; not a substitute for Android runtime tests."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CastlevaniaWiring(unittest.TestCase):
    def test_game_and_library_match(self):
        launcher = (ROOT / "android/src/com/retroaura/lasrecomp/CastlevaniaSnxBootActivity.java").read_text()
        self.assertIn('private static final String ID = "0100BA4026E94000"', launcher)
        self.assertIn('libcastlevania_snx.so', launcher)
        self.assertIn('ID + "_code.so"', launcher)
        self.assertIn('snx_source_dump', launcher)
        self.assertNotIn('copySnxExecutable(', launcher)

    def test_cli_does_not_pass_dump_as_game(self):
        game = (ROOT / "android/src/com/retroaura/lasrecomp/MarioSnxGameActivity.java").read_text()
        self.assertIn('"--game=" + base, "--source=" + dump.getAbsolutePath()', game)
        self.assertIn('"--fullscreen"', game)
        self.assertIn('SNX_EXTERNAL_ROMFS', game)

    def test_packaging_is_experimental_and_distinct(self):
        build = (ROOT / "compilar-mario-snx-runtime-termux.sh").read_text()
        launcher = (ROOT / "compilar-castlevania-snx-termux.sh").read_text()
        signed = (ROOT / "compilar-lasrecomp-termux.sh").read_text()
        self.assertIn('experimental/castlevania-belmonts-curse', build)
        self.assertIn('libcastlevania_snx.so', build)
        self.assertIn('CASTLEVANIA_SNX_CODE_SO', launcher)
        self.assertIn('LASRECOMP_SNX_MODULE_NAME', signed)
        manifest = (ROOT / "android/castlevania/AndroidManifest.xml").read_text()
        self.assertIn('com.retroaura.castlevania.snxruntime', manifest)
        self.assertIn('CastlevaniaSnxBootActivity', manifest)

if __name__ == "__main__":
    unittest.main(verbosity=2)
