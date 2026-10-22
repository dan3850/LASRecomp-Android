#!/usr/bin/env python3
"""Synthetic-only tests for locating the sixth shader in repeated exports."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from castlevania_extend_ryujinx import index_captures, failure_candidate


def capture(handle_reg=8, info_size=192):
    code = bytearray(8 * 660)
    # TEX.B encoding at the exact PC from the user's shader failure log.
    struct.pack_into("<Q", code, 651 * 8, (0xdeba << 48) | (handle_reg << 20) | 0x102)
    return (struct.pack("<4sIIIII", b"SNXS", 1, info_size, 4, len(code), 65536)
            + bytes(info_size) + code)


class ExtendCaptureTest(unittest.TestCase):
    def test_locate_exact_sixth_and_ignores_duplicate_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = (Path(root) / name for name in ("first.zip", "second.zip"))
            key = "ace294a500000001_4"
            with zipfile.ZipFile(a, "w") as z:
                z.writestr(f"shaders/{key}.snxs", capture())
            with zipfile.ZipFile(b, "w") as z:
                z.writestr(f"shaders/{key}.snxs", capture(info_size=256))
            corpus = index_captures([a, b])
            self.assertEqual(list(corpus), [key])
            self.assertEqual(failure_candidate(corpus), key)

    def test_reject_mismatched_register(self):
        with tempfile.TemporaryDirectory() as root:
            a = Path(root) / "invalid.zip"
            with zipfile.ZipFile(a, "w") as z:
                z.writestr("shaders/ace294a500000001_4.snxs", capture(handle_reg=22))
            corpus = index_captures([a])
            with self.assertRaisesRegex(ValueError, "sexto shader: 0 correspondencias exatas"):
                failure_candidate(corpus)

    def test_old_export_reports_missing_prefix_not_random_match(self):
        with tempfile.TemporaryDirectory() as root:
            a = Path(root) / "old-five-only.zip"
            with zipfile.ZipFile(a, "w") as z:
                z.writestr("shaders/214b89d400000001_4.snxs", capture())
            corpus = index_captures([a])
            with self.assertRaisesRegex(ValueError, "NAO esta presente nos ZIPs"):
                failure_candidate(corpus)

    def test_prefix_present_but_bad_texb_reports_opcode_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            a = Path(root) / "wrong-shader.zip"
            with zipfile.ZipFile(a, "w") as z:
                z.writestr("shaders/ace294a500000001_4.snxs", capture(handle_reg=22))
            corpus = index_captures([a])
            with self.assertRaisesRegex(ValueError, "codigo nao bate"):
                failure_candidate(corpus)

    def test_reject_ambiguous_target(self):
        with tempfile.TemporaryDirectory() as root:
            a = Path(root) / "two.zip"
            with zipfile.ZipFile(a, "w") as z:
                for suffix in (1, 2):
                    z.writestr(f"shaders/ace294a5{suffix:08x}_4.snxs", capture())
            with self.assertRaisesRegex(ValueError, "sexto shader: 2 correspondencias exatas"):
                failure_candidate(index_captures([a]))


if __name__ == "__main__":
    unittest.main()
