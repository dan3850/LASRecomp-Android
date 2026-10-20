#!/usr/bin/env python3
"""Plan and validate ARM64 SVC branch islands in private NSO memory.

This is an actual static rewrite of the 61 *real* SDK SVC instruction sites,
not execution of the Switch kernel: patched SVC branches lead to per-site
trap islands (MOVZ W16,#svc ; BRK #0x1234), deliberately NOT to fake HLE.
No NSO is modified or emitted; no ARM64 executed. Trampolines must later
be replaced with an ABI-safe Horizon kernel bridge before game execution.
"""
import argparse
from collections import Counter
from pathlib import Path
import struct

from nso import Nso

SVC_MASK = 0xFFE0001F
SVC_OPCODE = 0xD4000001
BRK_BLOCKED = 0xD4224680  # BRK #0x1234
BRANCH_OPCODE = 0x14000000
MAX_BRANCH_WORDS = 1 << 25


def svc_sites(nso):
    start, size = nso.text
    return [(off, (nso.u32(off) >> 5) & 0xFFFF)
            for off in range(start, start + size - size % 4, 4)
            if nso.u32(off) & SVC_MASK == SVC_OPCODE]


def encode_branch(source, target):
    if source % 4 or target % 4:
        raise ValueError("unaligned branch")
    delta = (target - source) // 4
    if not -MAX_BRANCH_WORDS <= delta < MAX_BRANCH_WORDS:
        raise ValueError(f"B out of 128MiB reach: {source:#x}->{target:#x}")
    return BRANCH_OPCODE | (delta & 0x3FFFFFF)


def plan_patch(nso):
    original = bytes(nso.image)
    sites = svc_sites(nso)
    if not sites:
        return 0
    # Islands are strictly after the existing NSO image, avoiding data/TLS
    # and the module's existing relocation destination ranges.
    image = bytearray(original)
    start = (len(image) + 15) & ~15
    image.extend(b"\0" * (start - len(image) + 8 * len(sites)))
    for i, (site, svc_number) in enumerate(sites):
        island = start + i * 8
        if struct.unpack_from("<I", original, site)[0] != (
            SVC_OPCODE | svc_number << 5
        ):
            raise ValueError(f"SVC changed at {site:#x}")
        # No rewriting to an actual service until ABI/register preservation
        # and Horizon semantics are implemented.
        branch = encode_branch(site, island)
        struct.pack_into("<I", image, site, branch)
        struct.pack_into("<I", image, island, 0x52800010 | (svc_number << 5))
        struct.pack_into("<I", image, island + 4, BRK_BLOCKED)
        # Decode the rewritten B and verify exact destination.
        imm = branch & 0x3FFFFFF
        if imm & (1 << 25):
            imm -= 1 << 26
        if site + imm * 4 != island:
            raise ValueError(f"branch target mismatch at {site:#x}")
        if (struct.unpack_from("<I", image, island)[0] >> 5) & 0xFFFF != svc_number:
            raise ValueError("service ID not preserved")
        if struct.unpack_from("<I", image, island + 4)[0] != BRK_BLOCKED:
            raise ValueError("unsupported service must trap")
    # All changes are confined to the original 61 SVC sites and appended
    # islands, and never persisted.
    changed = {off for off in range(len(original)) if image[off] != original[off]}
    allowed = {off for site, _ in sites for off in range(site, site + 4)}
    if not changed <= allowed:
        raise ValueError("non-SVC original bytes changed")
    print(f"SVC_PATCH_PLAN={len(sites)}")
    print(f"PRIVATE_IMAGE_BYTES={len(image)} island_start={start:#x}")
    print(f"svc_ids={','.join(hex(svc) for _, svc in sites)}")
    print("PASS: all real SVC sites replaced by verified B-to-island patches in memory.")
    print("BLOCKED: islands deliberately BRK; they are NOT an executable Horizon service bridge.")
    return len(sites)


def self_test():
    assert encode_branch(0, 16) == 0x14000004
    assert encode_branch(16, 0) == 0x17FFFFFC
    for source, target in ((1, 16), (0, 1), (0, 1 << 28)):
        try:
            encode_branch(source, target)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted invalid branch")
    print("PASS: branch encoding range and alignment unit tests")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    args = p.parse_args()
    self_test()
    root = args.game / "exefs" if (args.game / "exefs").is_dir() else args.game
    main_nso, sdk = Nso(root / "main"), Nso(root / "sdk")
    if svc_sites(main_nso):
        raise ValueError("unexpected SVC instructions in main; review required")
    if plan_patch(sdk) != 61:
        raise ValueError("SDK SVC count differs from the 61 previously audited")
    print("READ_ONLY: private patch discarded; original NSOs, APK and repo unchanged.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, AssertionError, ValueError, ImportError) as err:
        raise SystemExit(f"ERROR: {err}")
