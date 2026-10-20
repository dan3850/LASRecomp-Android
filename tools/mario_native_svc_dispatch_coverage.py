#!/usr/bin/env python3
"""Compare the *actual* SDK SVC IDs to the production Horizon dispatcher.

Read-only compatibility inventory. This does not claim that matching cases
are safe for directly executed guest code: rt_svc assumes a Cpu state and a
kernel-managed guest thread. A complete ARM64 save/restore bridge remains
required before any native SDK SVC call.
"""
import argparse
from pathlib import Path
import re

from nso import Nso
from mario_native_svc_island_plan import svc_sites


def implemented_cases(kernel):
    # Bound case scanning strictly to svc_impl(), not the rest of kernel.c.
    begin = kernel.find("static void svc_impl(Cpu *c, uint32_t imm, uint64_t pc) {")
    if begin < 0:
        raise ValueError("svc_impl function body not found")
    text = kernel[begin:]
    end = text.find("\n// Reboot, step 1:")
    if end < 0:
        raise ValueError("svc_impl end boundary not found")
    text = text[:end]
    return {int(item, 16) for item in re.findall(r"\bcase\s+0x([0-9A-Fa-f]+)\s*:", text)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    args = p.parse_args()
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    sdk = Nso(root / "sdk")
    raw_sites = svc_sites(sdk)
    if len(raw_sites) != 61:
        raise ValueError(f"SDK SVC set changed; expected 61, got {len(raw_sites)}")
    source = (Path(__file__).resolve().parent.parent / "runtime" / "kernel.c").read_text()
    supported = implemented_cases(source)
    in_sdk = {n for _, n in raw_sites}
    matched = sorted(in_sdk & supported)
    missing = sorted(in_sdk - supported)
    print(f"SDK_BUILD_ID={sdk.build_id}")
    print(f"SDK_SVC_SITES={len(raw_sites)}")
    print(f"SDK_UNIQUE_SVC_IDS={len(in_sdk)}")
    print(f"EXPLICIT_DISPATCH_CASES={len(matched)}")
    print("MATCHED_IDS=" + ",".join(hex(i) for i in matched))
    print(f"MISSING_DISPATCH_CASES={len(missing)}")
    print("MISSING_IDS=" + ",".join(hex(i) for i in missing))
    print("WARNING: case presence is NOT full implementation, ABI safety, or runtime readiness.")
    print("NEXT: guest register and TLS bridge + kernel thread lifecycle + missing SVC semantics.")
    print("READ_ONLY: no game instructions executed, images patched, or APK modified.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError, ImportError) as err:
        raise SystemExit(f"ERROR: {err}")
