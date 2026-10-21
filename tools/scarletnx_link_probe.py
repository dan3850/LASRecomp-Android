#!/usr/bin/env python3
"""Replay ONLY an existing Ninja link into a diagnostic copy, never rebuild it.

The old DSO and every object/archive remain untouched. Ninja's compdb -x expands
response files even when Ninja removed the physical .rsp after the last link.
This captures the supplying archive/member before correcting link flags.
"""
import argparse
import json
import shlex
import subprocess
from pathlib import Path

from scarletnx_elf_audit import Elf, audit


def link_argv(command, output):
    words = shlex.split(command)
    segments, segment = [], []
    for word in words:
        if word in ("&&", ";", "||"):
            segments.append(segment)
            segment = []
        else:
            segment.append(word)
    segments.append(segment)
    candidates = []
    for words in segments:
        if "-o" not in words or "-c" in words:
            continue
        i = words.index("-o") + 1
        if i < len(words) and Path(words[i]).name == "libscarletnx.so":
            candidates.append((words, i))
    if len(candidates) != 1:
        raise ValueError("cannot identify one ScarletNX linker invocation")
    words, i = candidates[0]
    if any(w.startswith("@") for w in words):
        raise ValueError("Ninja did not expand the linker response file")
    words[i] = str(output / "libscarletnx.so")
    words.extend([
        "-Wl,-Map=" + str(output / "before.map"), "-Wl,--cref",
        "-Wl,--why-extract=" + str(output / "before-why-extract.tsv"),
        "-Wl,--trace-symbol=getauxval", "-Wl,--trace-symbol=__bionic_getauxval",
        "-Wl,--trace-symbol=__aarch64_have_lse_atomics", "-Wl,--trace-symbol=__libc_init",
    ])
    return words


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--ninja", default="ninja")
    args = p.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        db = subprocess.run([args.ninja, "-C", str(args.build), "-t", "compdb", "-x"],
                            check=True, text=True, capture_output=True)
        rows = [row for row in json.loads(db.stdout)
                if Path(row["output"]).name == "libscarletnx.so"]
        if len(rows) != 1:
            raise ValueError("existing Ninja graph does not contain exactly one runtime link")
        row = rows[0]
        command = link_argv(row["command"], args.output)
        (args.output / "command.json").write_text(json.dumps(dict(
            original=row, diagnostic_argv=command), indent=2) + "\n")
        # Record the compiler driver's implicit -lc/-static-libstdc++ decisions.
        with (args.output / "driver.txt").open("w") as log:
            subprocess.run([*command, "-###"], cwd=row["directory"], stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        with (args.output / "link.log").open("w") as log:
            subprocess.run(command, cwd=row["directory"], stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        report = audit(args.output / "libscarletnx.so")
        original_path = Path(row["directory"]) / row["output"]
        original = Elf(original_path)
        replay = Elf(args.output / "libscarletnx.so")
        fingerprints = []
        for elf in (original, replay):
            fingerprints.append({(s["name"], elf.at(s["value"], s["size"]).hex())
                for s in elf.symbols if s["section"] and s["name"] == "getauxval"})
        report["getauxval_code_matches_original"] = bool(fingerprints[0]) and fingerprints[0] == fingerprints[1]
        (args.output / "elf.json").write_text(json.dumps(report, indent=2) + "\n")
        print("SCARLETNX_OLD_LINK_PROVENANCE:", args.output)
        for line in (args.output / "link.log").read_text().splitlines():
            if any(n in line for n in ("getauxval", "have_lse_atomics", "__libc_init")):
                print(line)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print("SCARLETNX_OLD_LINK_PROBE_UNAVAILABLE:", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
