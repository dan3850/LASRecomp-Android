#!/usr/bin/env python3
"""Opt-in Zelda Stable60 AOT/Home toggle for ScarletNX 34853ee (ABI 12).

This is an independently implemented two-BL LLVM branch, not an Eden source
copy or a binary NOP overwrite. Strict Build ID + original word guard lives
in module_llvm.c. The already booting code.so/APK must be preserved.
Apply/revert source mutations only inside the disposable ScarletNX cache.
"""
from __future__ import annotations

import argparse
from pathlib import Path

REPLACEMENTS = [
  {
    "path": "src/common/cpu/recompiler/llvm/ir_codegen.c",
    "old": "#define B ir->b\n",
    "new": "#define B ir->b\n\n/* Zelda Stable60 AOT: resolved from the verified main module before parallel codegen. */\nextern SnxU64 snx_zelda60_site_a, snx_zelda60_site_b;\nSnxU64 snx_zelda60_site_a, snx_zelda60_site_b;\n"
  },
  {
    "path": "src/common/cpu/recompiler/llvm/ir_codegen.c",
    "old": "            case SNX_FLOW_BL:\n                target = snx_a64_target(word, address);\n                ir_set_x(ir, 30, ir_i64(ir, next));\n                call(ir, codegen, target, 0);\n                check_return(ir, next);\n                break;",
    "new": "            case SNX_FLOW_BL:\n                target = snx_a64_target(word, address);\n                if ((address == snx_zelda60_site_a && word == 0x94009eb2u) ||\n                    (address == snx_zelda60_site_b && word == 0x9400020au)) {\n                    /* OFF executes the original BL. ON behaves as the mod's NOP,\n                       preserving LR and the rest of the guest CPU state. */\n                    LLVMBasicBlockRef original = ir_block(ir, \"zelda60_bl\");\n                    LLVMBasicBlockRef resume = ir_block(ir, \"zelda60_next\");\n                    LLVMValueRef slot = LLVMGetNamedGlobal(ir->mod, \"snx_zelda_stable60_enabled\");\n                    LLVMValueRef flag;\n                    if (!slot) {\n                        slot = LLVMAddGlobal(ir->mod, ir->t_i32, \"snx_zelda_stable60_enabled\");\n                        LLVMSetLinkage(slot, LLVMExternalLinkage);\n                    }\n                    flag = LLVMBuildLoad2(B, ir->t_i32, slot, \"zelda60_flag\");\n                    LLVMSetOrdering(flag, LLVMAtomicOrderingAcquire);\n                    LLVMSetAlignment(flag, 4);\n                    LLVMBuildCondBr(B, LLVMBuildICmp(B, LLVMIntEQ, flag, ir_i32(ir, 0), \"\"),\n                                    original, resume);\n                    LLVMPositionBuilderAtEnd(B, original);\n                    ir_set_x(ir, 30, ir_i64(ir, next));\n                    call(ir, codegen, target, 0);\n                    check_return(ir, next);\n                    LLVMBuildBr(B, resume);\n                    LLVMPositionBuilderAtEnd(B, resume);\n                } else {\n                    ir_set_x(ir, 30, ir_i64(ir, next));\n                    call(ir, codegen, target, 0);\n                    check_return(ir, next);\n                }\n                break;"
  },
  {
    "path": "src/nx/loader/module_llvm.c",
    "old": "#include <string.h>\n",
    "new": "#include <string.h>\n\n/* Only nonzero for an opt-in build whose main Build ID and both BL words match. */\nextern SnxU64 snx_zelda60_site_a, snx_zelda60_site_b;\n"
  },
  {
    "path": "src/nx/loader/module_llvm.c",
    "old": "    /* SNX_EXPORT const SnxModule* snx_module(void) */\n    fn = LLVMAddFunction(ir->mod, \"snx_module\", LLVMFunctionType(ir->t_ptr, NULL, 0, 0));",
    "new": "    /* Runtime-readable atomic flag; its initial value is always OFF. */\n    if (snx_zelda60_site_a && snx_zelda60_site_b) {\n        LLVMValueRef flag = LLVMAddGlobal(ir->mod, ir->t_i32, \"snx_zelda_stable60_enabled\");\n        LLVMSetInitializer(flag, ir_i32(ir, 0));\n        LLVMSetLinkage(flag, LLVMExternalLinkage);\n        LLVMSetVisibility(flag, LLVMDefaultVisibility);\n        LLVMSetAlignment(flag, 4);\n        if (ir->windows) LLVMSetDLLStorageClass(flag, LLVMDLLExportStorageClass);\n    }\n    /* SNX_EXPORT const SnxModule* snx_module(void) */\n    fn = LLVMAddFunction(ir->mod, \"snx_module\", LLVMFunctionType(ir->t_ptr, NULL, 0, 0));"
  },
  {
    "path": "src/nx/loader/module_llvm.c",
    "old": "    const char* exports[1];",
    "new": "    const char* exports[2];"
  },
  {
    "path": "src/nx/loader/module_llvm.c",
    "old": "    memset(&codegen, 0, sizeof(codegen));\n    memset(&q, 0, sizeof(q));",
    "new": "    memset(&codegen, 0, sizeof(codegen));\n    snx_zelda60_site_a = snx_zelda60_site_b = 0;\n    memset(&q, 0, sizeof(q));"
  },
  {
    "path": "src/nx/loader/module_llvm.c",
    "old": "    codegen.direct_svc = 1; /* the runtime's RtAPI.svcs (svc.c's g_svc64) */",
    "new": "    /* Fail closed: never generate a toggle for a different NSO revision. */\n    if (getenv(\"SNX_ZELDA60_AOT\") && !strcmp(getenv(\"SNX_ZELDA60_AOT\"), \"1\")) {\n        static const unsigned char expected_id[20] = {\n            0x90,0x9e,0x90,0x4a,0xf7,0x8a,0xc1,0xb8,0xde,0xef,\n            0xe9,0x7a,0xb2,0xcc,0xdb,0x51,0x96,0x8f,0x0e,0xc7\n        };\n        const SnxModuleImage* main_image = NULL;\n        SnxU32 a = 0, b = 0;\n        for (i = 0; i < loaded->module_count; ++i)\n            if (!strcmp(loaded->modules[i].name, \"main\")) {\n                main_image = &loaded->modules[i];\n                break;\n            }\n        if (!main_image || memcmp(main_image->build_id, expected_id, sizeof expected_id)) {\n            snx_error(\"Zelda60: main NSO Build ID mismatch; AOT unchanged\");\n            goto done;\n        }\n        snx_zelda60_site_a = main_image->base + 0x010196d8ull;\n        snx_zelda60_site_b = main_image->base + 0x010196f8ull;\n        (void)snx_codegen_word(&codegen, snx_zelda60_site_a, &a);\n        (void)snx_codegen_word(&codegen, snx_zelda60_site_b, &b);\n        if (a != 0x94009eb2u || b != 0x9400020au) {\n            snx_error(\"Zelda60: original BL instructions differ (%08x, %08x); AOT unchanged\", a, b);\n            goto done;\n        }\n        if (!options->quiet)\n            printf(\"Zelda60 AOT: verified main and two BL sites, toggle OFF by default\\n\");\n    }\n    codegen.direct_svc = 1; /* the runtime's RtAPI.svcs (svc.c's g_svc64) */"
  },
  {
    "path": "src/nx/loader/module_llvm.c",
    "old": "    exports[0] = \"snx_module\";\n    if (snx_link(inputs, n, exports, 1, base_name(build->output), &linked, error, sizeof(error))) {",
    "new": "    exports[0] = \"snx_module\";\n    if (snx_zelda60_site_a && snx_zelda60_site_b)\n        exports[1] = \"snx_zelda_stable60_enabled\";\n    if (snx_link(inputs, n, exports, snx_zelda60_site_a ? 2 : 1,\n                 base_name(build->output), &linked, error, sizeof(error))) {"
  },
  {
    "path": "src/nx/runtime/main.c",
    "old": "const SnxModule* g_mod;\nGuestFn* g_disp;\n",
    "new": "const SnxModule* g_mod;\nGuestFn* g_disp;\n\n/* Optional Zelda AOT switch, exported only by a version-verified recompile. */\nstatic void* g_game_lib;\nstatic int* g_zelda60_slot;\nstatic void zelda60_path(char* out, size_t size) {\n    snprintf(out, size, \"%s%s.zelda60\", g_confdir, g_exename);\n}\nint snx_zelda60_available(void) { return g_zelda60_slot != NULL; }\nint snx_zelda60_get(void) {\n    return g_zelda60_slot ? __atomic_load_n(g_zelda60_slot, __ATOMIC_ACQUIRE) != 0 : 0;\n}\nvoid snx_zelda60_set(int enabled) {\n    char path[sizeof g_confdir + sizeof g_exename + 32];\n    FILE* f;\n    if (!g_zelda60_slot) return;\n    __atomic_store_n(g_zelda60_slot, !!enabled, __ATOMIC_RELEASE);\n    zelda60_path(path, sizeof path);\n    f = fopen(path, \"w\");\n    if (f) {\n        fputs(enabled ? \"1\\n\" : \"0\\n\", f);\n        fclose(f);\n    }\n}\nstatic void zelda60_restore(void) {\n    char path[sizeof g_confdir + sizeof g_exename + 32];\n    char line[8] = {0};\n    FILE* f;\n    if (!g_zelda60_slot) return;\n    __atomic_store_n(g_zelda60_slot, 0, __ATOMIC_RELEASE);\n    zelda60_path(path, sizeof path);\n    f = fopen(path, \"r\");\n    if (!f) return;\n    if (fgets(line, sizeof line, f) && line[0] == '1')\n        __atomic_store_n(g_zelda60_slot, 1, __ATOMIC_RELEASE);\n    fclose(f);\n}\n"
  },
  {
    "path": "src/nx/runtime/main.c",
    "old": "    lib = plat_dl_open(path);\n    if (!lib) fatal(\"%s could not be loaded: %s\", path, plat_dl_error());",
    "new": "    lib = plat_dl_open(path);\n    if (!lib) fatal(\"%s could not be loaded: %s\", path, plat_dl_error());\n    g_game_lib = lib;"
  },
  {
    "path": "src/nx/runtime/main.c",
    "old": "    if (mod->abi != SNX_ABI)\n        fatal(\"The recompiled code is from another ScarletNX version: recompile the game with this one (%s)\",\n              module);\n    game_dirs();",
    "new": "    if (mod->abi != SNX_ABI)\n        fatal(\"The recompiled code is from another ScarletNX version: recompile the game with this one (%s)\",\n              module);\n    /* Do not expose the switch for another title or another main Build ID. */\n    if (g_game_lib && mod->title_id == 0x01006BB00C6F0000ull) {\n        static const unsigned char expected_id[20] = {\n            0x90,0x9e,0x90,0x4a,0xf7,0x8a,0xc1,0xb8,0xde,0xef,\n            0xe9,0x7a,0xb2,0xcc,0xdb,0x51,0x96,0x8f,0x0e,0xc7\n        };\n        for (u32 j = 0; j < mod->nmods; ++j)\n            if (!strcmp(mod->mods[j].name, \"main\") &&\n                !memcmp(mod->mods[j].build_id, expected_id, sizeof expected_id)) {\n                g_zelda60_slot = (int*)plat_dl_sym(g_game_lib, \"snx_zelda_stable60_enabled\");\n                break;\n            }\n    }\n    game_dirs();"
  },
  {
    "path": "src/nx/runtime/main.c",
    "old": "    ini_open(ini);\n    snprintf(g_gamename, sizeof g_gamename, \"%s\", base[0] ? base : g_exename);",
    "new": "    ini_open(ini);\n    zelda60_restore();\n    snprintf(g_gamename, sizeof g_gamename, \"%s\", base[0] ? base : g_exename);"
  },
  {
    "path": "src/nx/runtime/main.h",
    "old": "int snx_main(int argc, char** argv); /* runs the game the arguments or the program's name say; its exit status */",
    "new": "int snx_main(int argc, char** argv); /* runs the game the arguments or the program's name say; its exit status */\n/* Zelda AOT's version-checked Stable60 flag: absent on every other game. */\nint snx_zelda60_available(void);\nint snx_zelda60_get(void);\nvoid snx_zelda60_set(int enabled);"
  },
  {
    "path": "src/nx/runtime/platform/overlay.c",
    "old": "#include \"nx/runtime/platform/vpad.h\"\n",
    "new": "#include \"nx/runtime/platform/vpad.h\"\n#include \"nx/runtime/main.h\"\n"
  },
  {
    "path": "src/nx/runtime/platform/overlay.c",
    "old": "enum { M_CONTROLS, M_PADS, M_EXIT, M_COUNT };",
    "new": "enum { M_CONTROLS, M_PADS, M_STABLE60, M_EXIT, M_COUNT };"
  },
  {
    "path": "src/nx/runtime/platform/overlay.c",
    "old": "static int items(void) {\n    return page == PAGE_MAIN       ? M_COUNT",
    "new": "static int main_item(int i) {\n    return !snx_zelda60_available() && i >= M_STABLE60 ? i + 1 : i;\n}\nstatic int items(void) {\n    return page == PAGE_MAIN       ? M_COUNT - !snx_zelda60_available()"
  },
  {
    "path": "src/nx/runtime/platform/overlay.c",
    "old": "    if (page == PAGE_MAIN) {\n        static const char* const main_items[M_COUNT] = {SNX_VPAD_PAGE, SNX_GAMEPAD_PAGE, \"Exit\"};\n        snprintf(text, size, \"%s\", main_items[i]);\n        if (i != M_EXIT) snprintf(value, vsize, \">\");\n        return;\n    }",
    "new": "    if (page == PAGE_MAIN) {\n        static const char* const main_items[M_COUNT] = {\n            SNX_VPAD_PAGE, SNX_GAMEPAD_PAGE, \"Stable 60 FPS\", \"Exit\"\n        };\n        int m = main_item(i);\n        snprintf(text, size, \"%s\", main_items[m]);\n        if (m == M_STABLE60)\n            snprintf(value, vsize, \"%s\", snx_zelda60_get() ? \"ON\" : \"OFF\");\n        else if (m != M_EXIT)\n            snprintf(value, vsize, \">\");\n        return;\n    }"
  },
  {
    "path": "src/nx/runtime/platform/overlay.c",
    "old": "    if (page == PAGE_MAIN) {\n        if (step) return OVERLAY_NONE;\n        if (i == M_EXIT) return OVERLAY_EXIT;\n        page_open(i == M_PADS ? PAGE_PADS : PAGE_CONTROLS);\n        return OVERLAY_NONE;\n    }",
    "new": "    if (page == PAGE_MAIN) {\n        i = main_item(i);\n        if (step) return OVERLAY_NONE;\n        if (i == M_EXIT) return OVERLAY_EXIT;\n        if (i == M_STABLE60) {\n            snx_zelda60_set(!snx_zelda60_get());\n            return OVERLAY_NONE;\n        }\n        page_open(i == M_PADS ? PAGE_PADS : PAGE_CONTROLS);\n        return OVERLAY_NONE;\n    }"
  }
]

AOT = {
    "src/common/cpu/recompiler/llvm/ir_codegen.c",
    "src/nx/loader/module_llvm.c",
}
RUNTIME = {
    "src/nx/runtime/main.c",
    "src/nx/runtime/main.h",
    "src/nx/runtime/platform/overlay.c",
}


def patch(source: Path, mode: str, revert: bool = False, check: bool = False) -> None:
    paths = AOT if mode == "aot" else RUNTIME if mode == "runtime" else AOT | RUNTIME
    updates: dict[Path, str] = {}
    for relative in sorted(paths):
        target = source / relative
        original = target.read_text(encoding="utf-8")
        content = original
        changes = [x for x in REPLACEMENTS if x["path"] == relative]
        if revert:
            changes.reverse()
        for change in changes:
            before = change["new"] if revert else change["old"]
            after = change["old"] if revert else change["new"]
            if content.count(before) == 1:
                content = content.replace(before, after, 1)
            elif content.count(after) == 1:
                continue  # Already at the requested state.
            else:
                raise ValueError(
                    f"{relative}: unexpected source; refusing partial or ambiguous patch"
                )
        updates[target] = content

    if not check:
        for target, content in updates.items():
            if target.read_text(encoding="utf-8") != content:
                target.write_text(content, encoding="utf-8")
    state = "REVERT" if revert else "APPLY"
    print(f"ZELDA60_{state}: {mode}, {len(updates)} files, "
          f"{'checked only' if check else 'updated'}; ABI 12 unchanged")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pinned ScarletNX 34853ee tree")
    parser.add_argument("--mode", choices=["aot", "runtime", "all"], required=True)
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    patch(args.source, args.mode, args.revert, args.check)


if __name__ == "__main__":
    main()
