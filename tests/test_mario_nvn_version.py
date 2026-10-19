"""Exercise the real NVN integer table against Mario's device startup gate."""
import ctypes
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MarioNvnVersionTests(unittest.TestCase):
    def test_title_versions_and_device_bootstrap_gate(self):
        source = (ROOT / 'runtime/nvn/objects.c').read_text()
        start = source.index('static uint32_t device_integer(')
        end = source.index('\nNVN(', start)
        body = source[start:end]
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            c = folder / 'version.c'
            c.write_text('#include <stdint.h>\n' + body +
                         '\nuint32_t query(uint32_t key) { return device_integer(key); }\n')
            tables = []
            for mario in (False, True):
                library = folder / ('mario.so' if mario else 'zelda.so')
                subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Werror',
                                *(['-DLASRECOMP_MARIO_TEST'] if mario else []),
                                str(c), '-o', str(library)], check=True)
                loaded = ctypes.CDLL(str(library))
                loaded.query.argtypes = [ctypes.c_uint32]
                loaded.query.restype = ctypes.c_uint32
                tables.append([loaded.query(key) for key in range(66)])
            zelda, mario = tables
            self.assertEqual(zelda[:2], [53, 207])
            # The observed guest returns before publishing its graphics object
            # unless major == 0x35 and minor >= 0x139.
            self.assertTrue(mario[0] == 0x35 and mario[1] >= 0x139)
            self.assertEqual(mario[2:], zelda[2:])


if __name__ == '__main__':
    unittest.main(verbosity=2)
