#!/usr/bin/env python3
"""Rewrite a minimal Switch A64 TLS-read function to Android host-call code.

Input: raw little-endian ARM64 instructions exactly
    mrs x0, tpidr_el0
    ret
Output: native A64 function with preserved LR, call to a local absolute
host-function thunk, and return. The host function address is supplied by
the caller at runtime in the last 8 bytes of the output.

This is intentionally a *narrow* first rewrite, not a general NSO parser.
"""
from __future__ import annotations
import argparse
import struct
from pathlib import Path

MRS_X0_TPIDR_EL0 = 0xD53BD040
RET = 0xD65F03C0
# stp x29,x30,[sp,#-16]!; mov w0,#1; bl thunk; ldp x29,x30,[sp],#16;
# ret; ldr x16,[pc,#12]; br x16; nop; .quad host_address
REWRITTEN = (
    0xA9BF7BFD, 0x52800020, 0x94000003, 0xA8C17BFD,
    RET, 0x58000070, 0xD61F0200, 0xD503201F,
)

def rewrite(source: bytes) -> bytes:
    if len(source) != 8:
        raise ValueError("expected exactly two AArch64 instructions")
    words = struct.unpack("<2I", source)
    if words != (MRS_X0_TPIDR_EL0, RET):
        raise ValueError(f"unsupported A64 input: {words!r}")
    return struct.pack("<8IQ", *REWRITTEN, 0)

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    args.output.write_bytes(rewrite(args.input.read_bytes()))
    print(f"NX_REWRITE_OK bytes={args.output.stat().st_size}")

if __name__ == "__main__":
    main()
