"""Test that native source preparation never edits original Ryujinx code or rebuilds it needlessly."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / "tools/ryujinx-nativeaot/prepare_source.py"
SPEC = importlib.util.spec_from_file_location("native_ryujinx_preparer", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareTest(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        upstream = root / "nxnative"
        source = upstream / "dm/gfx/tools/dmsh_xlate/Program.cs"
        project = upstream / "dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Ryujinx.Graphics.Shader.csproj"
        source.parent.mkdir(parents=True)
        project.parent.mkdir(parents=True)
        code = "// upstream, keep original\nstatic class SwshXlate {\n sealed class Accessor : IGpuAccessor {}\n}"
        source.write_text(code)
        project.write_text("<Project/>")
        bridge = root / "bridge"
        bridge.mkdir()
        (bridge / "BridgeExports.cs").write_text("// native wrapper")
        (bridge / "ScarletAdapter.cs").write_text("// dynamic Vulkan adapter")
        (bridge / "RyujinxShaderNative.csproj").write_text("<Project/>")
        return upstream, bridge, code

    def test_no_upstream_modification_and_caching(self):
        with tempfile.TemporaryDirectory() as path:
            upstream, bridge, original = self.fixture(path)
            generated = Path(path) / "out"
            MODULE.prepare(upstream, bridge, generated)
            staged = generated / "Program.Native.cs"
            self.assertIn("static partial class SwshXlate", staged.read_text())
            self.assertEqual((upstream / "dm/gfx/tools/dmsh_xlate/Program.cs").read_text(), original)
            first_stamp = staged.stat().st_mtime_ns
            MODULE.prepare(upstream, bridge, generated)
            self.assertEqual(staged.stat().st_mtime_ns, first_stamp)

    def test_refuse_unknown_upstream_layout(self):
        with tempfile.TemporaryDirectory() as path:
            upstream, bridge, _ = self.fixture(path)
            original = upstream / "dm/gfx/tools/dmsh_xlate/Program.cs"
            original.write_text("static class Renamed { }")
            with self.assertRaisesRegex(ValueError, "upstream Ryujinx launcher changed"):
                MODULE.prepare(upstream, bridge, Path(path) / "out")


if __name__ == "__main__":
    unittest.main()
