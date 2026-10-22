import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('termux_v2', Path(__file__).resolve().parents[1] / 'tools/termux_ryujinx_v2.py')
V2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V2)


class SignedApkIntegrity(unittest.TestCase):
    def test_accepts_matching_payloads_and_rejects_stale_runtime_or_native(self):
        identity = 'SNX_RYU_SOURCE_SHA256=' + 'a' * 64
        revision = 'b' * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'identity.json'
            manifest.write_text(json.dumps({'source_identity': identity}))
            library = root / 'lib.so'
            library.write_bytes(b'new native')
            apk = root / 'test.apk'
            for runtime, native, valid in [
                ((identity + revision + 'RYUJINX_NATIVE_V2').encode(), b'new native', True),
                ((identity + 'RYUJINX_NATIVE_V2').encode(), b'new native', False),
                ((revision + 'RYUJINX_NATIVE_V2').encode(), b'new native', False),
                ((identity + revision + 'RYUJINX_NATIVE_V2').encode(), b'old native', False),
            ]:
                with zipfile.ZipFile(apk, 'w') as archive:
                    archive.writestr('lib/arm64-v8a/libscarletnx.so', runtime)
                    archive.writestr('lib/arm64-v8a/libRyujinxShaderNative.so', native)
                if valid:
                    V2.verify_apk(apk, manifest, revision, library)
                else:
                    with self.assertRaises(ValueError):
                        V2.verify_apk(apk, manifest, revision, library)


if __name__ == '__main__':
    unittest.main()
