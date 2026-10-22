"""Synthetic ZIP/ELF tests: reject wrong architectures and corrupt checksums."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "tools/ryujinx-nativeaot/extract_artifact.py"
SPEC = importlib.util.spec_from_file_location("ryujinx_aot_extractor", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def fake_so(machine=183, kind=3):
    buf = bytearray(2048)
    buf[:6] = bytes((127, 69, 76, 70, 2, 1))
    struct.pack_into("<H", buf, 16, kind)
    struct.pack_into("<H", buf, 18, machine)
    return bytes(buf)


def archive(path, payload, checksum=None):
    checksum = checksum or hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(MOD.SONAME, payload)
        z.writestr("README.txt", "Ryujinx NativeAOT Android ARM64")
        z.writestr("SHA256SUMS", checksum + "  " + MOD.SONAME + "\n")


class ArtifactTest(unittest.TestCase):
    def test_valid_arm64_library_passes_sha(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "artifact.zip"
            data = fake_so()
            archive(path, data)
            out = Path(d) / "private" / MOD.SONAME
            self.assertEqual(MOD.extract(path, out), out)
            self.assertEqual(out.read_bytes(), data)

    def test_wrong_architecture_fails_without_writing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "artifact.zip"
            archive(path, fake_so(machine=62))  # AMD64
            out = Path(d) / MOD.SONAME
            with self.assertRaisesRegex(ValueError, "ARM64"):
                MOD.extract(path, out)
            self.assertFalse(out.exists())

    def test_bad_sha_fails_without_install(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "artifact.zip"
            archive(path, fake_so(), "0" * 64)
            out = Path(d) / MOD.SONAME
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                MOD.extract(path, out)
            self.assertFalse(out.exists())

    def test_incorrect_elf_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "artifact.zip"
            archive(path, fake_so(kind=2))  # executable, not shared
            with self.assertRaisesRegex(ValueError, "shared object"):
                MOD.extract(path, Path(d) / MOD.SONAME)


if __name__ == "__main__":
    unittest.main()
