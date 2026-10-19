"""Function discovery and instruction census for an NSO module."""
import struct
import sys
from collections import Counter

import capstone
from nso import Nso, R_AARCH64_RELATIVE


def read_encoded(img, off, enc, pc_base):
    fmt = enc & 0x0F
    app = enc & 0x70
    if fmt == 0x0B:      # sdata4
        v, size = struct.unpack_from('<i', img, off)[0], 4
    elif fmt == 0x03:    # udata4
        v, size = struct.unpack_from('<I', img, off)[0], 4
    elif fmt in (0x0C, 0x04):
        v, size = struct.unpack_from('<q' if fmt == 0x0C else '<Q', img, off)[0], 8
    else:
        raise ValueError(f'unsupported encoding {enc:#x}')
    if app == 0x10:
        v += off
    elif app == 0x30:
        v += pc_base
    return v, size


def eh_frame_functions(n):
    """Function start addresses from .eh_frame_hdr's binary search table."""
    img, hdr = n.image, n.eh_start
    if not hdr or hdr >= len(img):
        return []
    ver, ptr_enc, cnt_enc, tbl_enc = img[hdr:hdr + 4]
    off = hdr + 4
    _, sz = read_encoded(img, off, ptr_enc, hdr)
    off += sz
    count, sz = read_encoded(img, off, cnt_enc, hdr)
    off += sz
    starts = []
    for _ in range(count):
        loc, sz = read_encoded(img, off, tbl_enc, hdr)
        off += sz
        _, sz = read_encoded(img, off, tbl_enc, hdr)
        off += sz
        starts.append(loc)
    return starts



def _uleb(img, off, end):
    value = 0
    shift = 0
    while off < end and shift < 70:
        byte = img[off]
        off += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, off
        shift += 7
    raise ValueError("invalid ULEB128")


def eh_frame_intervals(n):
    """Read FDE PC ranges through the .eh_frame_hdr table, conservatively.

    Only CIE augmentation zR and the known fixed-width pointer encodings
    are accepted. Unrecognized FDEs are skipped; no guessed ranges are used.
    """
    img, hdr = n.image, n.eh_start
    if not hdr or hdr + 4 > len(img):
        return {}, Counter()
    _, ptr_enc, cnt_enc, tbl_enc = img[hdr:hdr + 4]
    off = hdr + 4
    _, size = read_encoded(img, off, ptr_enc, hdr)
    off += size
    count, size = read_encoded(img, off, cnt_enc, hdr)
    off += size
    stats = Counter()
    ranges = {}
    text_lo, text_size = n.text
    text_hi = text_lo + text_size
    for _ in range(count):
        try:
            start, size = read_encoded(img, off, tbl_enc, hdr)
            off += size
            fde, size = read_encoded(img, off, tbl_enc, hdr)
            off += size
            length = struct.unpack_from("<I", img, fde)[0]
            if length == 0 or length == 0xffffffff or fde + 4 + length > len(img):
                raise ValueError("invalid FDE length")
            cie_delta = struct.unpack_from("<I", img, fde + 4)[0]
            cie = fde + 4 - cie_delta
            cie_length = struct.unpack_from("<I", img, cie)[0]
            if cie_length == 0 or cie_length == 0xffffffff or cie + 4 + cie_length > len(img):
                raise ValueError("invalid CIE length")
            if struct.unpack_from("<I", img, cie + 4)[0] != 0:
                raise ValueError("not a CIE")
            version = img[cie + 8]
            if version not in (1, 3, 4):
                raise ValueError("unsupported CIE version")
            end = cie + 4 + cie_length
            aug_end = img.index(0, cie + 9, end)
            augmentation = bytes(img[cie + 9:aug_end]).decode("ascii")
            if not augmentation.startswith("z") or any(ch not in "R" for ch in augmentation[1:]):
                raise ValueError("unsupported CIE augmentation")
            cursor = aug_end + 1
            if version == 4:
                cursor += 2
            _, cursor = _uleb(img, cursor, end)
            # data_alignment is SLEB128; only its byte count is needed.
            while cursor < end:
                byte = img[cursor]
                cursor += 1
                if not byte & 128:
                    break
            else:
                raise ValueError("invalid data alignment")
            _, cursor = _uleb(img, cursor, end)
            aug_size, cursor = _uleb(img, cursor, end)
            aug_data_end = cursor + aug_size
            if aug_data_end > end:
                raise ValueError("CIE augmentation overflow")
            encoding = img[cursor] if "R" in augmentation else 0x00
            if encoding == 0x00:
                raise ValueError("absolute pointer encoding unsupported")
            pc, width = read_encoded(img, fde + 8, encoding, hdr)
            # FDE address_range has the format but not the application bits.
            span, _ = read_encoded(img, fde + 8 + width, encoding & 0x0f, hdr)
            if pc != start or span <= 0 or pc % 4 or span % 4 or not (text_lo <= pc < pc + span <= text_hi):
                raise ValueError("FDE range mismatch")
            if pc in ranges and ranges[pc] != pc + span:
                raise ValueError("conflicting FDE ranges")
            ranges[pc] = pc + span
            stats["valid"] += 1
        except (ValueError, IndexError, struct.error, UnicodeError):
            stats["skipped"] += 1
    return ranges, stats


def discover(n):
    text_lo, text_hi = n.text[0], n.text[0] + n.text[1]
    in_text = lambda a: text_lo <= a < text_hi and a % 4 == 0
    funcs = {}
    for a in eh_frame_functions(n):
        if in_text(a):
            funcs[a] = 'eh'
    for name, info, shndx, value, size in n.syms:
        if shndx and in_text(value) and (info & 0xF) == 2:
            funcs.setdefault(value, 'sym')
    # Code pointers stored in data (vtables, callbacks)
    ptr_targets = set()
    for off, typ, sym, add in n.relocs:
        if typ == R_AARCH64_RELATIVE and in_text(add):
            ptr_targets.add(add)
    for a in ptr_targets:
        funcs.setdefault(a, 'ptr')
    # BL targets
    code = bytes(n.image[text_lo:text_hi])
    words = struct.unpack(f'<{len(code) // 4}I', code)
    for i, w in enumerate(words):
        if (w & 0xFC000000) == 0x94000000:
            imm = w & 0x03FFFFFF
            if imm & 0x02000000:
                imm -= 0x04000000
            t = text_lo + i * 4 + imm * 4
            if in_text(t):
                funcs.setdefault(t, 'bl')
    return funcs, words


def census(n, words):
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    c = Counter()
    bad = 0
    code = struct.pack(f'<{len(words)}I', *words)
    off = 0
    while off < len(code):
        got = False
        for ins in md.disasm_lite(code[off:], n.text[0] + off):
            c[ins[2]] += 1
            off += 4
            got = True
        if off < len(code):   # undecodable word: skip it
            bad += 1
            off += 4
    return c, bad


if __name__ == '__main__':
    n = Nso(sys.argv[1])
    funcs, words = discover(n)
    print(f'functions: {len(funcs)}  by source: {dict(Counter(funcs.values()))}')
    if '--census' in sys.argv:
        c, bad = census(n, words)
        print(f'instructions: {sum(c.values())}  undecodable words: {bad}  distinct mnemonics: {len(c)}')
        print(' '.join(f'{m}:{k}' for m, k in c.most_common()))
