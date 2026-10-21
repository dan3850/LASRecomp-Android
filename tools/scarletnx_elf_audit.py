#!/usr/bin/env python3
"""Inspect Android ELF linkage, including LOCAL symbols hidden by version scripts.

No third-party Python modules are required. --report-only records an old/broken
ELF without approving it for packaging. Linker maps/--why-extract and archive nm
output preserve the supplying objects, not just the final export names.
"""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path


PLATFORM = {
    "getauxval", "__bionic_getauxval", "__libc_auxv", "__libc_init",
    "memcpy", "memmove", "memset", "strcmp", "newlocale",
}
WATCH = ("getauxval", "init_have_lse_atomics", "__aarch64_have_lse_atomics",
         "__libc_shared_globals", "__libc_auxv", "__libc_init")
TRACE = b"SCARLETNX_MAIN_ENTERED"


def android_relocations(data, rela=True):
    """Decode APS2 groups as specified by Bionic's linker_reloc_iterators.h."""
    if data[:4] != b"APS2":
        raise ValueError("invalid Android packed relocation header")
    cursor = 4

    def sleb():
        nonlocal cursor
        value = shift = 0
        while True:
            if cursor >= len(data) or shift > 63:
                raise ValueError("invalid packed relocation SLEB128")
            byte = data[cursor]
            cursor += 1
            value |= (byte & 127) << shift
            shift += 7
            if not byte & 128:
                return value - (1 << shift) if byte & 64 else value

    count, offset = sleb(), sleb()
    if count < 0 or count > len(data) * 64:
        raise ValueError("invalid packed relocation count")
    emitted = info = addend = 0
    while emitted < count:
        size, flags = sleb(), sleb()
        if size <= 0 or size > count - emitted:
            raise ValueError("invalid packed relocation group size")
        delta = sleb() if flags & 2 else None
        if flags & 1:
            info = sleb()
        if not rela and flags & 8:
            raise ValueError("unexpected addend in packed REL")
        if flags & 8:
            if flags & 4:
                addend += sleb()  # once per group, not once per relocation
        else:
            addend = 0
        for _ in range(size):
            offset += delta if delta is not None else sleb()
            if not flags & 1:
                info = sleb()
            if flags & 8 and not flags & 4:
                addend += sleb()
            yield offset, info, addend if rela else None
            emitted += 1


class Elf:
    """Small ELF64-LE reader; virtual addresses are never treated as file offsets."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if self.data[:6] != b"\x7fELF\x02\x01":
            raise ValueError("expected ELF64 little endian: " + str(path))
        h = self.unpack("16sHHIQQQIHHHHHH", 0)
        self.kind, self.machine = h[1:3]
        if not h[12] or h[11] < 64:
            raise ValueError("ELF section headers required (audit before stripping)")
        self.sections = []
        for i in range(h[12]):
            v = self.unpack("IIQQQQIIQQ", h[6] + i * h[11])
            self.sections.append(dict(zip(
                ("name_offset", "type", "flags", "addr", "offset", "size",
                 "link", "info", "align", "entsize"), v)))
        strings = self.section_bytes(self.sections[h[13]])
        for s in self.sections:
            s["name"] = self.string(strings, s["name_offset"])
        self.symbols, self.tables = [], {}
        for i, s in enumerate(self.sections):
            if s["type"] not in (2, 11):
                continue
            strings = self.section_bytes(self.sections[s["link"]])
            table = []
            for off in range(0, s["size"], s["entsize"] or 24):
                name, info, other, ndx, value, size = self.unpack("IBBHQQ", s["offset"] + off)
                sym = dict(name=self.string(strings, name), type=info & 15,
                           bind=info >> 4, visibility=other & 3, section=ndx,
                           value=value, size=size, table=s["name"])
                table.append(sym)
                if sym["name"]:
                    self.symbols.append(sym)
            self.tables[i] = table
        versions = {}
        for s in self.sections:
            if s["type"] != 0x6ffffffe:  # SHT_GNU_verneed
                continue
            strings = self.section_bytes(self.sections[s["link"]])
            off = 0
            while off < s["size"]:
                _, count, file, aux, next_need = self.unpack("HHIII", s["offset"] + off)
                aux_off = off + aux
                for _ in range(count):
                    _, _, index, name, next_aux = self.unpack("IHHII", s["offset"] + aux_off)
                    versions[index & 0x7fff] = dict(version=self.string(strings, name),
                                                   version_file=self.string(strings, file))
                    aux_off += next_aux
                if not next_need:
                    break
                off += next_need
        for s in self.sections:
            if s["type"] == 0x6fffffff:  # SHT_GNU_versym
                for i, sym in enumerate(self.tables.get(s["link"], [])):
                    index = self.unpack("H", s["offset"] + i * 2)[0] & 0x7fff
                    sym.update(versions.get(index, {}))
        self.relocations = []
        for s in self.sections:
            if s["type"] in (19, 0x6fffff00):  # RELR / Android RELR
                offset = 0
                for pos in range(0, s["size"], 8):
                    entry = self.unpack("Q", s["offset"] + pos)[0]
                    if entry & 1:
                        slots = [offset + i * 8 for i in range(63) if entry & (2 << i)]
                        offset += 63 * 8
                    else:
                        slots = [entry]
                        offset = entry + 8
                    for slot in slots:
                        raw = self.at(slot, 8)
                        self.relocations.append(dict(offset=slot,
                            type=1027 if self.machine == 183 else 8,
                            addend=int.from_bytes(raw, "little"), symbol="", section=s["name"]))
                continue
            if s["type"] in (0x60000001, 0x60000002):
                entries = android_relocations(self.section_bytes(s), s["type"] == 0x60000002)
            elif s["type"] in (4, 9):
                fmt = "QQq" if s["type"] == 4 else "QQ"
                entries = (self.unpack(fmt, s["offset"] + off)
                    for off in range(0, s["size"], s["entsize"] or struct.calcsize("<" + fmt)))
            else:
                continue
            for v in entries:
                table = self.tables.get(s["link"], [])
                sym_index = v[1] >> 32
                self.relocations.append(dict(
                    offset=v[0], type=v[1] & 0xffffffff,
                    addend=v[2] if len(v) == 3 else None,
                    symbol=table[sym_index]["name"] if sym_index < len(table) else "",
                    section=s["name"]))
        self.needed = []
        self.dynamic = []
        for s in self.sections:
            if s["type"] == 6:
                strings = self.section_bytes(self.sections[s["link"]])
                for off in range(0, s["size"], s["entsize"] or 16):
                    tag, value = self.unpack("qQ", s["offset"] + off)
                    self.dynamic.append((tag, value))
                    if tag == 1:
                        self.needed.append(self.string(strings, value))
        self.build_ids = []
        for s in self.sections:
            if s["type"] != 7:
                continue
            off = 0
            while off + 12 <= s["size"]:
                namesz, descsz, typ = self.unpack("III", s["offset"] + off)
                start = s["offset"] + off + 12
                name = self.data[start:start + namesz].rstrip(b"\0")
                desc = start + ((namesz + 3) & ~3)
                if name == b"GNU" and typ == 3:
                    self.build_ids.append(self.data[desc:desc + descsz].hex())
                off += 12 + ((namesz + 3) & ~3) + ((descsz + 3) & ~3)

    def unpack(self, fmt, off):
        return struct.unpack_from("<" + fmt, self.data, off)

    @staticmethod
    def string(data, off):
        return data[off:data.index(b"\0", off)].decode("utf-8", errors="replace")

    def section_bytes(self, s):
        return self.data[s["offset"]:s["offset"] + s["size"]]

    def at(self, addr, size):
        for s in self.sections:
            if s["type"] != 8 and s["addr"] <= addr and addr + size <= s["addr"] + s["size"]:
                off = s["offset"] + addr - s["addr"]
                return self.data[off:off + size]
        return b""

    def names_at(self, addr):
        return sorted({s["name"] for s in self.symbols if s["section"] and s["value"] == addr})

    def constructors(self):
        entries = []
        relative = 1027 if self.machine == 183 else 8
        relocs = {r["offset"]: r for r in self.relocations}
        for s in self.sections:
            if s["type"] != 14:  # SHT_INIT_ARRAY
                continue
            for off in range(0, s["size"], 8):
                address = s["addr"] + off
                target = self.unpack("Q", s["offset"] + off)[0]
                r = relocs.get(address)
                if r and r["type"] == relative and r["addend"] is not None:
                    target = r["addend"]
                entries.append(dict(index=off // 8, slot=hex(address), target=hex(target),
                                    names=self.names_at(target), relocation=r))
        return entries

    def lse_branches(self):
        if self.machine != 183:
            return []
        result = []
        seen = set()
        for s in self.symbols:
            if "init_have_lse_atomics" not in s["name"] or not s["section"] or s["value"] in seen:
                continue
            seen.add(s["value"])
            code = self.at(s["value"], s["size"])
            calls = []
            for off in range(0, len(code) - 3, 4):
                word = struct.unpack_from("<I", code, off)[0]
                if word & 0x7c000000 == 0x14000000:  # B / BL immediate
                    imm = word & 0x03ffffff
                    if imm & 0x02000000:
                        imm -= 0x04000000
                    target = s["value"] + off + imm * 4
                    calls.append(dict(pc=hex(s["value"] + off), target=hex(target),
                                      names=self.names_at(target)))
            result.append(dict(symbol=s, branches=calls))
        return result


def audit(path, require_main=False, require_trace=False):
    elf = Elf(path)
    problems = []
    if elf.kind != 3 or elf.machine != 183:
        problems.append("runtime must be an AArch64 ET_DYN library")
    definitions = [s for s in elf.symbols if s["section"] and
                   (s["name"].split("@")[0] in PLATFORM or
                    "__libc_shared_globals" in s["name"])]
    if definitions:
        problems.append("private platform libc definitions linked into DSO: " +
                        ", ".join(sorted({s["name"] for s in definitions})))
    imports = [s for s in elf.symbols if s["name"].split("@")[0] == "getauxval" and
               s["table"] == ".dynsym" and s["section"] == 0]
    if not imports:
        problems.append("getauxval must be an undefined dynamic import from Android libc")
    if imports and not any(s.get("version_file") == "libc.so" and
                           s.get("version", "").startswith("LIBC") for s in imports):
        problems.append("getauxval import is not version-bound to libc.so (LIBC)")
    aux_relocs = [r for r in elf.relocations if r["symbol"].split("@")[0] == "getauxval"]
    if not aux_relocs:
        problems.append("no dynamic relocation to the imported getauxval")
    if "libc.so" not in elf.needed:
        problems.append("missing DT_NEEDED libc.so")
    if require_main:
        for name in ("main", "JNI_OnLoad"):
            if not any(s["name"] == name and s["table"] == ".dynsym" and s["section"] and
                       s["bind"] in (1, 2) and s["visibility"] in (0, 3) for s in elf.symbols):
                problems.append("missing public entry: " + name)
    if require_trace and TRACE not in elf.data:
        problems.append("runtime lacks the real main() entry trace")
    return dict(path=str(elf.path.resolve()), sha256=hashlib.sha256(elf.data).hexdigest(),
                size=len(elf.data), needed=elf.needed, problems=problems,
                build_ids=elf.build_ids, dynamic_tags=elf.dynamic,
                init_functions=[dict(address=hex(value), names=elf.names_at(value))
                                for tag, value in elf.dynamic if tag == 12],
                platform_definitions=definitions,
                watched_symbols=[s for s in elf.symbols if any(n in s["name"] for n in WATCH)],
                ifunc_symbols=[s for s in elf.symbols if s["type"] == 10],
                irelative=[r for r in elf.relocations if r["type"] == 1032],
                getauxval_relocations=aux_relocs, init_array=elf.constructors(),
                lse_branches=elf.lse_branches(),
                packed_relocation_sections=[s["name"] for s in elf.sections
                    if s["type"] in (19, 0x60000001, 0x60000002, 0x6fffff00)])


def cxx_problems(directory):
    """Catch a renamed original C++ DSO being substituted for Termux LLVM's C++ ABI."""
    directory = Path(directory)
    provider = directory / "libsnx_c++_shared.so"
    if not provider.is_file():
        return ["missing pinned libsnx_c++_shared.so"]
    defined = {s["name"] for s in Elf(provider).symbols if s["table"] == ".dynsym" and s["section"]}
    problems = []
    for path in sorted(directory.glob("*.so")):
        if path == provider:
            continue
        elf = Elf(path)
        if any(s["section"] and (s["name"] in ("getauxval", "__bionic_getauxval", "__libc_auxv") or
                                 "__libc_shared_globals" in s["name"]) for s in elf.symbols):
            problems.append(path.name + " carries a private auxiliary-vector libc implementation")
        if "libc++_shared.so" in elf.needed:
            problems.append(path.name + " still imports the unpinned C++ SONAME")
        missing = sorted({s["name"] for s in elf.symbols if s["table"] == ".dynsym" and
                          not s["section"] and s["bind"] != 2 and
                          ("St6__ndk1" in s["name"] or "St3__1" in s["name"]) and
                          s["name"] not in defined})
        if missing:
            problems.append(path.name + ": C++ provider lacks " + ", ".join(missing[:12]))
    return problems


def diagnostic(command, output):
    """Preserve optional tool evidence, including partial output and failures.

    These tools do not decide whether the runtime passes the ELF policy. In
    particular, a candidate .a may be a linker script, an unsupported archive,
    or contain bitcode that this nm cannot read. A failed index proves nothing
    about the absence of private libc symbols in the final shared library.
    """
    result = dict(command=command, output=str(output), status="unavailable",
                  returncode=None)
    try:
        run = subprocess.run(command, text=True, errors="replace",
                             capture_output=True, check=False)
    except OSError as error:
        result["error"] = str(error)
        output.write_text(str(error) + "\n")
        return result, ""
    output.write_text("stdout:\n" + run.stdout + "\nstderr:\n" + run.stderr)
    result.update(returncode=run.returncode,
                  status="complete" if run.returncode == 0 else "incomplete")
    if run.returncode:
        result["error"] = run.stderr.strip()[-1000:] or "tool returned no stderr"
    return result, run.stdout


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("elf", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report-only", action="store_true")
    p.add_argument("--require-main", action="store_true")
    p.add_argument("--require-trace", action="store_true")
    p.add_argument("--archive", action="append", type=Path, default=[])
    p.add_argument("--nm", default="llvm-nm")
    p.add_argument("--cxx-dir", type=Path)
    p.add_argument("--link-log", type=Path)
    p.add_argument("--link-map", type=Path)
    p.add_argument("--why-extract", type=Path)
    args = p.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = audit(args.elf, args.require_main, args.require_trace)
        report["actual_link_evidence"] = {}
        for evidence in (args.link_log, args.link_map, args.why_extract):
            if evidence is not None:
                with evidence.open(errors="replace") as stream:
                    report["actual_link_evidence"][str(evidence)] = [line.rstrip()
                        for line in stream if any(n in line for n in WATCH)]
        if args.cxx_dir:
            report["problems"].extend(cxx_problems(args.cxx_dir))
        report["archive_providers"] = []
        report["archive_diagnostics"] = []
        report["supporting_diagnostics"] = []
        report["diagnostic_warnings"] = []
        # Do not lose the mandatory ELF findings if optional tools fail later.
        args.output.write_text(json.dumps(report, indent=2) + "\n")

        def record(result):
            if result["status"] in ("incomplete", "unavailable"):
                report["diagnostic_warnings"].append(
                    f'{result["command"][0]}: {result["status"]}, '
                    f'exit={result["returncode"]}; {result["error"]}; '
                    f'full output: {result["output"]}')

        for index, archive in enumerate(dict.fromkeys(args.archive)):
            if not archive.is_file():
                report["archive_diagnostics"].append(
                    dict(path=str(archive), status="missing"))
                continue
            raw = args.output.with_name(args.output.stem + f"-archive-{index}.txt")
            result, stdout = diagnostic(
                [args.nm, "-A", "--defined-only", str(archive)], raw)
            result["path"] = str(archive)
            result["resolved_path"] = str(archive.resolve())
            providers = [line for line in stdout.splitlines()
                         if any(n in line for n in WATCH)]
            if result["status"] == "complete":
                report["archive_providers"].extend(providers)
            else:
                # Partial nm output must never look like a complete index.
                result["partial_providers"] = providers
            report["archive_diagnostics"].append(result)
            record(result)
        # These are supporting evidence only; the policy above reads the binary.
        for tool, flags, suffix in (("llvm-readelf", ["-aW"], "readelf"),
                                    ("llvm-objdump", ["-d", "--disassemble-symbols=init_have_lse_atomics,getauxval"], "disasm")):
            if shutil.which(tool):
                result, _ = diagnostic([tool, *flags, str(args.elf)],
                    args.output.with_suffix("." + suffix + ".txt"))
                report["supporting_diagnostics"].append(result)
                record(result)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        for warning in report["diagnostic_warnings"]:
            print("ELF_AUDIT_DIAGNOSTIC_WARNING:", warning)
        for problem in report["problems"]:
            print("ELF_AUDIT:", problem)
        print("SCARLETNX_ELF_AUDIT:", "FAIL" if report["problems"] else "OK", args.output)
        return 0 if args.report_only or not report["problems"] else 1
    except (ValueError, OSError, struct.error) as error:
        print("ELF_AUDIT_ERROR:", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
