/* SPDX-License-Identifier: MIT
 * The C side of the real Ryujinx NativeAOT shader translator. ABI v1.
 * This describes translation, NOT a Vulkan-ready pipeline. The returned
 * SPIR-V descriptor decorations and graphics state still require mapping.
 */
#ifndef SNX_RYUJINX_NATIVE_ABI_H
#define SNX_RYUJINX_NATIVE_ABI_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t *spirv;            /* allocated by .NET NativeAOT */
    size_t spirv_bytes;
    uint8_t *reflection_json;  /* UTF-8, NUL-terminated */
    size_t reflection_bytes;
    uint8_t *error;            /* UTF-8 on translation failure */
    size_t error_bytes;
} SnxRyuResult;

typedef int (*SnxRyuApiVersion)(void);
typedef int (*SnxRyuTranslate)(const uint8_t *maxwell, size_t maxwell_bytes,
                               const uint8_t *job_json, size_t job_bytes,
                               SnxRyuResult *result);
typedef void (*SnxRyuFree)(SnxRyuResult *result);

/* Symbols exported by the NativeAOT shared library:
 *   snx_ryu_api_version
 *   snx_ryu_translate_v1
 *   snx_ryu_free_v1
 *
 * Return values for Translate: 0 success, -1 invalid argument,
 * -2 translator error (result->error optional). Always call Free once for
 * any output whose result struct was passed to Translate.
 *
 * No pointers to managed/GC memory escape across the API; all allocations
 * are owned by the NativeAOT library and freed through snx_ryu_free_v1.
 */
#ifdef __cplusplus
}
#endif
#endif
