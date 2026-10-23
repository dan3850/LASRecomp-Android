#!/usr/bin/env python3
"""Diagnostic only: log Zelda's real guest-main NSO build ID and two original words.

Unlike scanning arbitrary bytes in the 251 MB host AOT ELF, this reads the
SnxModInfo descriptor the runtime actually checked against the XCI/NSP.
Never changes CPU instructions, game memory, AOT code, version, ABI, or FPS.
"""
import argparse
from pathlib import Path

ORIGINAL = '    if (loader_load()) fatal("Could not load the game executables. See the .log for details.");'
INSERT = r'''    /* Zelda 1.1.0 Stable 60fps v3 preflight: diagnostic ONLY. */
    if (g_mod->title_id == 0x01006BB00C6F0000ull) {
        static const u32 sites[] = {0x010196D8u, 0x010196F8u};
        static const char* expected = "602492BC6DC3533DF6BC57E572520C96F89319EC";
        const SnxModInfo* main_mod = NULL;
        for (u32 i = 0; i < g_mod->nmods; i++) {
            if (!strcmp(g_mod->mods[i].name, "main")) {
                main_mod = &g_mod->mods[i];
                break;
            }
        }
        if (main_mod) {
            char build_id[41];
            for (u32 i = 0; i < 20; i++)
                snprintf(build_id + 2 * i, sizeof build_id - 2 * i,
                         "%02X", main_mod->build_id[i]);
            LOG("ZELDA60_MAIN_BUILD_ID=%s\n", build_id);
            LOG("ZELDA60_EXPECTED_BUILD_ID=%s\n", expected);
            LOG("ZELDA60_BUILD_ID_MATCH=%s\n", !strcmp(build_id, expected) ? "YES" : "NO");
            LOG("ZELDA60_MAIN_BASE=0x%llx TEXT=0x%x+0x%x\n",
                (unsigned long long)main_mod->base, main_mod->text_off, main_mod->text_size);
            for (u32 i = 0; i < sizeof sites / sizeof sites[0]; i++) {
                const u64 site = sites[i];
                const u64 end = (u64)main_mod->text_off + main_mod->text_size;
                if (site < main_mod->text_off || site + 4 > end || site + 4 > main_mod->size) {
                    LOG("ZELDA60_SITE main+0x%08x NOT_IN_TEXT\n", sites[i]);
                    continue;
                }
                u32 original_word = 0;
                memcpy(&original_word, GP(main_mod->base + site), sizeof original_word);
                LOG("ZELDA60_SITE main+0x%08x PC=0x%llx ORIGINAL_WORD=%08x\n",
                    sites[i], (unsigned long long)(main_mod->base + site), original_word);
            }
            LOG("ZELDA60_PATCH_STATE=OFF (diagnostic only, no change to game)\n");
        } else {
            LOG("ZELDA60_MAIN_MODULE_MISSING\n");
        }
    }
'''
WITH_DIAG = ORIGINAL + "\n" + INSERT

def run(source: Path, revert: bool):
    path = source / "src/nx/runtime/main.c"
    s = path.read_text(encoding="utf-8")
    if revert:
        if s.count(WITH_DIAG) == 1:
            modified = s.replace(WITH_DIAG, ORIGINAL, 1)
        elif s.count(ORIGINAL) == 1 and "ZELDA60_MAIN_BUILD_ID" not in s:
            modified = s
        else:
            raise ValueError("Refusing to revert unfamiliar ScarletNX main.c")
    elif s.count(WITH_DIAG) == 1:
        modified = s
    elif s.count(ORIGINAL) == 1 and "ZELDA60_MAIN_BUILD_ID" not in s:
        modified = s.replace(ORIGINAL, WITH_DIAG, 1)
    else:
        raise ValueError("Unknown ScarletNX main.c; do not apply diagnostic")
    if modified != s:
        path.write_text(modified, encoding="utf-8")
    print("ZELDA60_RUNTIME_DIAG:", "REVERTED" if revert else "APPLIED",
          "(read-only; ABI 12; no guest instruction patches)")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--revert", action="store_true")
    args = p.parse_args()
    run(args.source, args.revert)
