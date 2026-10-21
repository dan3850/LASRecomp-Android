#!/usr/bin/env python3
"""Real ELF/linker regressions; no Mario assets, device, or full runtime build.

The broken fixture deliberately models a private libc auxiliary-vector pointer.
It is never packaged. A native subprocess proves why hiding the symbol is not
a fix; AArch64 ELF fixtures verify the production guard and constructor audit.
"""
import ast
import contextlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from scarletnx_elf_audit import Elf, audit, cxx_problems, main as audit_main
from scarletnx_link_probe import link_argv
from patch_scarletnx_android_link import BEGIN, ENTRY_TRACE, patch


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True,
                          capture_output=True, **kwargs)


class SyntaxAndPipeline(unittest.TestCase):
    def test_complete_bash_and_embedded_python(self):
        paths = [ROOT / n for n in ("compilar-mario-snx-romfs-termux.sh",
                                    "compilar-mario-snx-runtime-termux.sh")]
        count = 0
        for path in paths:
            run(["bash", "-n", path])
            source = path.read_text()
            for match in re.finditer(r"<<'PY'[^\n]*\n(.*?)^PY$", source, re.M | re.S):
                ast.parse(match[1], filename=str(path) + ":heredoc")
                count += 1
        self.assertEqual(count, sum(path.read_text().count("<<'PY'") for path in paths))
        self.assertGreater(count, 0)
        for name in ("scarletnx_elf_audit.py", "scarletnx_link_probe.py",
                     "patch_scarletnx_android_link.py", "patch_scarletnx_romfs.py"):
            ast.parse((ROOT / "tools" / name).read_text(), filename=name)

    def test_llvm_patch_repairs_legacy_nesting_and_is_idempotent(self):
        source = (ROOT / "compilar-mario-snx-romfs-termux.sh").read_text()
        code = re.search(r'python3 - "\$LLVM_CMAKE" <<\'PY\'\n(.*?)^PY$', source, re.M | re.S)[1]
        original = '''if(ANDROID OR IOS OR (APPLE AND LLVM_DIR AND NOT SNX_LLVM_CONFIG))
endif()
snx_llvm_query(SNX_LLVM_LIBS --libs ${SNX_LLVM_COMPONENTS})
    snx_llvm_query(SNX_LLVM_DISASM_LIBS --libs aarch64disassembler aarch64desc aarch64info)
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llvm.cmake"
            path.write_text(original)
            run([sys.executable, "-", path], input=code)
            wanted = path.read_text()
            legacy = code.replace("while b in s:\n    s = s.replace(b, a, 1)\nif s.count(a) == 1:", "if a in s:")
            # Simulate the old match-in-else behavior twice, then repair it.
            for _ in range(2):
                run([sys.executable, "-", path], input=legacy)
            self.assertNotEqual(path.read_text(), wanted)
            run([sys.executable, "-", path], input=code)
            self.assertEqual(path.read_text(), wanted)
            modified = path.stat().st_mtime_ns
            run([sys.executable, "-", path], input=code)
            self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_forensic_command_changes_only_output_and_diagnostic_flags(self):
        old = ': && /tool/clang++ -shared -Wl,-Bsymbolic "an object.o" -o libscarletnx.so libcached.a && :'
        words = link_argv(old, Path("/evidence"))
        self.assertEqual(words[:8], ["/tool/clang++", "-shared", "-Wl,-Bsymbolic",
                                     "an object.o", "-o", "/evidence/libscarletnx.so",
                                     "libcached.a", "-Wl,-Map=/evidence/before.map"])
        self.assertIn("-Wl,--trace-symbol=getauxval", words)
        with self.assertRaisesRegex(ValueError, "response file"):
            link_argv('clang++ -shared @lost.rsp -o libscarletnx.so', Path('/evidence'))

    def test_native_main_marker_is_exported_in_current_attempt(self):
        game = (ROOT / "android/src/com/retroaura/lasrecomp/MarioSnxGameActivity.java").read_text()
        boot = (ROOT / "android/src/com/retroaura/lasrecomp/MarioBootActivity.java").read_text()
        self.assertIn('nativeSetenv("SNX_BOOT_TRACE"', game)
        self.assertIn('new File(getFilesDir(), "mario-snx-native.log").delete()', boot)
        self.assertIn('"mario-snx-launch.log", "mario-snx-native.log"', boot)


class AArch64Link(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("clang") and shutil.which("ld.lld"):
            cls.cc, cls.ld = ["clang"], ["ld.lld"]
        elif importlib.util.find_spec("ziglang"):
            cls.cc = [sys.executable, "-m", "ziglang", "cc"]
            cls.ld = [sys.executable, "-m", "ziglang", "ld.lld"]
        else:
            raise unittest.SkipTest("requires clang+lld or Zig for real AArch64 ELF fixtures")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p = Path(cls.tmp.name)
        cls.compile("system", '''
struct Aux { unsigned long key, value; };
static struct Aux vector[] = {{16, 256}, {0, 0}};
unsigned long getauxval(unsigned long type) {
    for (struct Aux *v = vector; v->key; ++v) if(v->key == type) return v->value;
    return 0;
}
''')
        (cls.p / "libc.map").write_text("LIBC { global: getauxval; local: *; };\n")
        run([*cls.ld, "-shared", "--build-id=sha1", "-soname", "libc.so", cls.p / "system.o",
             "--version-script=" + str(cls.p / "libc.map"), "-o", cls.p / "libc.so"])
        cls.compile("private", '''
struct Aux { unsigned long key, value; };
static struct Aux *private_vector;
unsigned long getauxval(unsigned long type) {
    for (struct Aux *v = private_vector; v->key; ++v) if(v->key == type) return v->value;
    return 0;
}
''')
        cls.compile("entry", '''
extern unsigned long getauxval(unsigned long);
_Bool __aarch64_have_lse_atomics;
__attribute__((constructor(90))) static void init_have_lse_atomics(void) {
    __aarch64_have_lse_atomics = (getauxval(16) & 256) != 0;
}
__attribute__((visibility("default"))) const char *main_trace = "SCARLETNX_MAIN_ENTERED";
__attribute__((visibility("default"))) int main(void) {return __aarch64_have_lse_atomics;}
__attribute__((visibility("default"))) int JNI_OnLoad(void) {return 0x10006;}
''')
        (cls.p / "runtime.map").write_text("{ global: main; JNI_OnLoad; local: *; };\n")
        # LLD defaults vary (fast 8-byte vs SHA-1). This fixture explicitly
        # tests SHA-1; the production reader accepts arbitrary Build ID sizes.
        common = [*cls.ld, "-shared", "--build-id=sha1", "-Bsymbolic", cls.p / "entry.o",
                  "--version-script=" + str(cls.p / "runtime.map")]
        run([*common, cls.p / "private.o", "-o", cls.p / "broken.so"])
        run([*common, "--no-as-needed", cls.p / "libc.so", "-o", cls.p / "fixed.so"])

    @classmethod
    def compile(cls, name, text):
        (cls.p / (name + ".c")).write_text(text)
        run([*cls.cc, "-target", "aarch64-freestanding", "-fPIC", "-ffreestanding", "-O1",
             "-c", cls.p / (name + ".c"), "-o", cls.p / (name + ".o")])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_hidden_getauxval_fails_even_with_export_allowlist(self):
        elf = Elf(self.p / "broken.so")
        self.assertFalse(any(s["name"] == "getauxval" and s["table"] == ".dynsym" for s in elf.symbols))
        report = audit(self.p / "broken.so", require_main=True, require_trace=True)
        self.assertTrue(any(s["name"] == "getauxval" and s["bind"] == 0
                            for s in report["platform_definitions"]))
        self.assertTrue(report["problems"])
        self.assertTrue(any("getauxval" in call["names"] for f in report["lse_branches"]
                            for call in f["branches"]))

    def test_fixed_import_versions_relocations_and_constructor(self):
        report = audit(self.p / "fixed.so", require_main=True, require_trace=True)
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["platform_definitions"], [])
        self.assertEqual(report["needed"], ["libc.so"])
        imported = next(s for s in report["watched_symbols"] if s["name"] == "getauxval")
        self.assertEqual((imported["section"], imported["version_file"], imported["version"]), (0, "libc.so", "LIBC"))
        self.assertTrue(any(r["type"] == 1026 for r in report["getauxval_relocations"]))
        self.assertTrue(any("init_have_lse_atomics" in c["names"] for c in report["init_array"]))
        self.assertEqual(len(report["build_ids"][0]), 40)

    @unittest.skipUnless(shutil.which("llvm-nm") or shutil.which("nm"), "requires nm")
    def test_nm_rejecting_candidate_does_not_override_final_elf_policy(self):
        # Real nm returns nonzero for a GNU linker script named .a. This
        # reproduces the collector failure without guessing the phone's format.
        nm = shutil.which("llvm-nm") or shutil.which("nm")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            archive = path / "libatomic.a"
            archive.write_text("INPUT ( libc.so )\n")
            for elf, report_only, expected in (("fixed.so", False, 0),
                                                ("broken.so", False, 1),
                                                ("broken.so", True, 0)):
                with self.subTest(elf=elf, report_only=report_only):
                    output = path / f"{elf}-{report_only}.json"
                    args = [str(self.p / elf), "--output", str(output),
                            "--archive", str(archive), "--nm", nm]
                    if report_only:
                        args.append("--report-only")
                    with contextlib.redirect_stdout(io.StringIO()) as console:
                        self.assertEqual(audit_main(args), expected)
                    report = json.loads(output.read_text())
                    candidate, = report["archive_diagnostics"]
                    self.assertEqual(candidate["status"], "incomplete")
                    self.assertNotEqual(candidate["returncode"], 0)
                    self.assertTrue(Path(candidate["output"]).read_text().strip())
                    self.assertTrue(candidate["error"])
                    self.assertTrue(report["diagnostic_warnings"])
                    self.assertIn("ELF_AUDIT_DIAGNOSTIC_WARNING", console.getvalue())
                    self.assertEqual(bool(report["problems"]), elf == "broken.so")
                    self.assertEqual(report["archive_providers"], [])

    def test_partial_nm_output_is_retained_as_incomplete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            nm = path / "partial-nm"
            partial = "libatomic.a(cpu.o): 0 T init_have_lse_atomics"
            nm.write_text("#!" + shutil.which("sh") + "\nprintf '%s\\n' '" + partial + "'\n"
                          "printf '%s\\n' 'unsupported member' >&2\nexit 1\n")
            nm.chmod(0o755)
            output = path / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit_main([str(self.p / "fixed.so"),
                    "--output", str(output), "--archive", str(self.p / "entry.o"),
                    "--nm", str(nm)]), 0)
            report = json.loads(output.read_text())
            candidate, = report["archive_diagnostics"]
            self.assertEqual(candidate["partial_providers"], [partial])
            self.assertEqual(report["archive_providers"], [])
            raw = Path(candidate["output"]).read_text()
            self.assertIn(partial, raw)
            self.assertIn("unsupported member", raw)
            self.assertEqual(report["problems"], [])

    def test_missing_nm_preserves_core_report_and_records_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit_main([str(self.p / "fixed.so"),
                    "--output", str(output), "--archive", str(self.p / "entry.o"),
                    "--nm", str(Path(tmp) / "absent-nm")]), 0)
            report = json.loads(output.read_text())
            candidate, = report["archive_diagnostics"]
            self.assertEqual(candidate["status"], "unavailable")
            self.assertIsNone(candidate["returncode"])
            self.assertIn("absent-nm", Path(candidate["output"]).read_text())
            self.assertTrue(report["diagnostic_warnings"])
            self.assertEqual(report["problems"], [])

    def test_supporting_tools_cannot_discard_primary_elf_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"

            def unavailable(*args, **kwargs):
                # The ELF report already exists before external tools run.
                self.assertEqual(json.loads(output.read_text())["problems"], [])
                raise OSError("external dump unavailable")

            with mock.patch("scarletnx_elf_audit.shutil.which", return_value="tool"), \
                 mock.patch("scarletnx_elf_audit.subprocess.run", side_effect=unavailable), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit_main([str(self.p / "fixed.so"),
                                            "--output", str(output)]), 0)
            report = json.loads(output.read_text())
            self.assertEqual(len(report["supporting_diagnostics"]), 2)
            self.assertEqual(len(report["diagnostic_warnings"]), 2)
            self.assertEqual(report["problems"], [])

    def test_android_packed_relocations_and_relr_preserve_constructor_audit(self):
        for packing in ("android", "relr", "android+relr"):
            with self.subTest(packing=packing):
                output = self.p / (packing + ".so")
                run([*self.ld, "-shared", "-Bsymbolic", self.p / "entry.o",
                     "--pack-dyn-relocs=" + packing, "--no-as-needed", self.p / "libc.so",
                     "--version-script=" + str(self.p / "runtime.map"), "-o", output])
                report = audit(output, require_main=True, require_trace=True)
                self.assertEqual(report["problems"], [])
                self.assertTrue(report["packed_relocation_sections"])
                self.assertTrue(any("init_have_lse_atomics" in c["names"] for c in report["init_array"]))

    def test_stripped_private_definition_cannot_pass(self):
        # Remove .symtab at link time as a packaged/stripped ELF would do.
        run([*self.ld, "-shared", "-Bsymbolic", "-s", self.p / "entry.o", self.p / "private.o",
             "--version-script=" + str(self.p / "runtime.map"), "-o", self.p / "stripped.so"])
        report = audit(self.p / "stripped.so")
        self.assertIn("getauxval must be an undefined dynamic import from Android libc", report["problems"])

    @unittest.skipUnless(shutil.which("ar"), "requires archive tool")
    def test_static_libc_shadow_and_actual_archive_member_provenance(self):
        directory = self.p / "shadow"
        directory.mkdir(exist_ok=True)
        run(["ar", "rcs", directory / "libc.a", self.p / "private.o"])
        why = self.p / "why-extract.tsv"
        trace = run([*self.ld, "-shared", "-Bsymbolic", self.p / "entry.o",
            "--version-script=" + str(self.p / "runtime.map"),
            "--why-extract=" + str(why), "--trace-symbol=getauxval",
            "-L" + str(directory), "-lc", "-o", self.p / "shadowed.so"])
        self.assertIn("libc.a(private.o)", trace.stdout + trace.stderr)
        self.assertIn("getauxval", why.read_text())
        self.assertTrue(audit(self.p / "shadowed.so")["platform_definitions"])
        # A named shared import before the archives prevents extraction of the
        # conflicting definition, even when the general search dir remains.
        run([*self.ld, "-shared", "-Bsymbolic", "--no-as-needed", self.p / "libc.so",
             self.p / "entry.o", "-L" + str(directory), "-lc",
             "--version-script=" + str(self.p / "runtime.map"), "-o", self.p / "unshadowed.so"])
        self.assertEqual(audit(self.p / "unshadowed.so")["problems"], [])

    def test_ifunc_is_visible_in_report(self):
        # freestanding Clang can ignore the C IFUNC attribute; specify the GNU
        # ELF symbol type in assembly so this tests the real STT_GNU_IFUNC field.
        (self.p / "ifunc.S").write_text('''.text
.globl memset
.type memset, %gnu_indirect_function
memset:
    adr x0, copy_impl
    ret
.type copy_impl, %function
copy_impl:
    ret
.globl call_memset
.type call_memset, %function
call_memset:
    b memset
''')
        run([*self.cc, "-target", "aarch64-freestanding", "-c", self.p / "ifunc.S",
             "-o", self.p / "ifunc.o"])
        (self.p / "ifunc.map").write_text('{ global: call_memset; local: *; };\n')
        run([*self.ld, "-shared", "-Bsymbolic", self.p / "ifunc.o",
             "--version-script=" + str(self.p / "ifunc.map"), "-o", self.p / "ifunc.so"])
        report = audit(self.p / "ifunc.so")
        self.assertTrue(any(s["name"] == "memset" for s in report["ifunc_symbols"]))
        self.assertTrue(any(s["name"] == "memset" for s in report["platform_definitions"]))
        self.assertTrue(any(r["type"] == 1032 for r in report["irelative"]))

    def test_patcher_upgrades_legacy_once_and_preserves_bsymbolic(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            cmake = source / "src/nx/CMakeLists.txt"
            entry = source / "src/nx/runtime/entry.c"
            entry.parent.mkdir(parents=True)
            cmake.write_text('if(ANDROID)\n    add_library(scarletnx SHARED runtime/entry.c)\n'
                '    target_link_options(scarletnx PRIVATE -Wl,-Bsymbolic)\n'
                '    target_link_options(scarletnx PRIVATE "-Wl,--version-script=/old.map")\nendif()\n')
            entry.write_text('#include <string.h>\nint main(int argc, char** argv) {\nreturn 0;\n}\n')
            args = (source, self.p / "libc.so", self.p / "fixed.so", self.p / "runtime.map", source / "evidence")
            patch(*args)
            wanted = (cmake.read_text(), entry.read_text())
            times = (cmake.stat().st_mtime_ns, entry.stat().st_mtime_ns)
            patch(*args)
            self.assertEqual((cmake.read_text(), entry.read_text()), wanted)
            self.assertEqual((cmake.stat().st_mtime_ns, entry.stat().st_mtime_ns), times)
            self.assertEqual(cmake.read_text().count(BEGIN), 1)
            self.assertIn('-Wl,-Bsymbolic', cmake.read_text())
            self.assertIn('LINK_DEPENDS', cmake.read_text())
            self.assertEqual(entry.read_text().count(ENTRY_TRACE), 1)

    def test_cxx_provider_mismatch_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.compile("cxx", 'int _ZNSt6__ndk16neededEv(void) {return 1;}\n')
            run([*self.ld, "-shared", "-soname", "libsnx_c++_shared.so", self.p / "cxx.o",
                 "-o", directory / "libsnx_c++_shared.so"])
            self.compile("needs", 'extern int _ZNSt6__ndk16neededEv(void); int use(void) {return _ZNSt6__ndk16neededEv();}\n')
            run([*self.ld, "-shared", self.p / "needs.o", directory / "libsnx_c++_shared.so",
                 "-o", directory / "libuser.so"])
            self.assertEqual(cxx_problems(directory), [])
            # Replace with an ABI-incomplete provider, keeping the SONAME.
            run([*self.ld, "-shared", "-soname", "libsnx_c++_shared.so", self.p / "entry.o",
                 "-o", directory / "libsnx_c++_shared.so"])
            self.assertTrue(any('provider lacks' in s for s in cxx_problems(directory)))


@unittest.skipUnless(shutil.which("gcc"), "native subprocess regression requires GCC")
class NativeLoad(unittest.TestCase):
    def test_hiding_static_auxv_reader_crashes_but_system_import_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "entry.c").write_text('extern unsigned long getauxval(unsigned long);\n'
                'volatile unsigned long hwcap;\n'
                '__attribute__((constructor(101))) static void init_have_lse_atomics(void) {hwcap=getauxval(16);}\n')
            (path / "private.c").write_text('static volatile unsigned long *private_auxv;\n'
                'unsigned long getauxval(unsigned long type) {return private_auxv[type];}\n')
            (path / "exports.map").write_text('{ global: hwcap; local: *; };\n')
            common = ["gcc", "-shared", "-fPIC", "-Wl,-Bsymbolic",
                      "-Wl,--version-script=" + str(path / "exports.map"), path / "entry.c"]
            run([*common, path / "private.c", "-o", path / "broken.so"])
            run([*common, "-o", path / "fixed.so"])
            code = ('import ctypes,resource,sys; resource.setrlimit(resource.RLIMIT_CORE,(0,0)); '
                    'lib=ctypes.CDLL(sys.argv[1]); assert ctypes.c_ulong.in_dll(lib,"hwcap").value')
            broken = subprocess.run([sys.executable, "-c", code, str(path / "broken.so")], capture_output=True)
            fixed = subprocess.run([sys.executable, "-c", code, str(path / "fixed.so")], capture_output=True)
            self.assertEqual(broken.returncode, -11)
            self.assertEqual(fixed.returncode, 0, fixed.stderr.decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
