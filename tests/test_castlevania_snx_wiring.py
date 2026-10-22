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
        self.assertIn('unset LASRECOMP_MARIO_PROFILE LASRECOMP_GAME_SO', build)
        self.assertNotIn('build/private-mario-full-test', build)
        self.assertNotIn('mario_profile_config.h', build)
        self.assertIn('LASRECOMP_NEO_CONTROLS=0', build)
        self.assertIn('CASTLEVANIA_SNX_CODE_SO', launcher)
        self.assertIn('LASRECOMP_SNX_MODULE_NAME', signed)
        manifest = (ROOT / "android/castlevania/AndroidManifest.xml").read_text()
        self.assertIn('com.retroaura.castlevania.snxruntime', manifest)
        self.assertIn('CastlevaniaSnxBootActivity', manifest)

    def test_graphics_diagnostics_are_not_tail_only(self):
        log_report = (ROOT / "android/src/com/retroaura/lasrecomp/ScarletNxLogReport.java").read_text()
        launcher = (ROOT / "android/src/com/retroaura/lasrecomp/CastlevaniaSnxBootActivity.java").read_text()
        self.assertIn("BufferedReader", log_report)
        self.assertIn('low.contains("not translated")', log_report)
        self.assertIn('low.contains("fswzadd")', log_report)
        self.assertIn("ScarletNxLogReport.build(getFilesDir(), ID)", launcher)
        self.assertIn('"snx-log-export"', launcher)

    def test_shader_runtime_isolated_and_source_reverted(self):
        shader = (ROOT / "compilar-castlevania-shader-termux.sh").read_text()
        compiler = (ROOT / "compilar-mario-snx-romfs-termux.sh").read_text()
        self.assertIn("scarletnx-castlevania-shader-build/libscarletnx.so", shader)
        self.assertIn("Castlevania-SNX-Runtime-ANTES-FSWZADD.apk", shader)
        self.assertIn("trap restore_source EXIT", shader)
        self.assertIn("SCARLETNX_RUNTIME_OUT", compiler)
        self.assertIn("SCARLETNX_CASTLEVANIA_FSWZADD", compiler)


if __name__ == "__main__":
    unittest.main(verbosity=2)
