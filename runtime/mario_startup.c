// Mario SDK startup: execute the exported guest Start with its actual ABI.
#ifdef LASRECOMP_MARIO_TEST
#include "mario_startup.h"
#include "hle.h"
#include "kernel.h"

// The loader owns module readiness; no guest rtld image is being executed.
static void modules_ready(Cpu *c) {
    (void)c;
    LOG("[mario-boot] rtld ready callback\n");
}

static void module_array(Cpu *c, uint64_t address, uint64_t bytes, bool reverse) {
    if (bytes % 8) FATAL("[mario-boot] invalid module constructor/finalizer array\n");
    uint64_t count = bytes / 8;
    const uint64_t *array = (const uint64_t *)(uintptr_t)address;
    for (uint64_t i = 0; i < count; i++) {
        uint64_t fn = array[reverse ? count - i - 1 : i];
        if (fn) guest_call(c, fn);
    }
}

static void initialize_modules(Cpu *c) {
    // With main/sdk only, sdk is main's dependency. DT_INIT itself runs its
    // module's init_array; only use the array directly when DT_INIT is absent.
    for (int i = g_nmodules - 1; i >= 0; i--) {
        Module *m = &g_modules[i];
        LOG("[mario-boot] init %s (DT_INIT=%llx array entries=%llu)\n",
            m->name, (unsigned long long)m->init, (unsigned long long)(m->init_array_sz / 8));
        if (m->init) guest_call(c, m->init);
        else module_array(c, m->init_array, m->init_array_sz, false);
    }
}

static void finalize_modules(Cpu *c) {
    // Reverse dependency order, and reverse each module's fini_array.
    for (int i = 0; i < g_nmodules; i++) {
        Module *m = &g_modules[i];
        LOG("[mario-boot] fini %s\n", m->name);
        if (m->fini) guest_call(c, m->fini);
        else module_array(c, m->fini_array, m->fini_array_sz, true);
    }
}

void mario_startup(uint64_t stack_size, int priority) {
    const char *symbol = "_ZN2nn4init5StartEmmPFvvES2_S2_";
    uint64_t start = loader_find_symbol(symbol);
    bool finalizer = start != 0;
    if (!start) {
        symbol = "_ZN2nn4init5StartEmmPFvvES2_";
        start = loader_find_symbol(symbol);
    }
    if (!start) FATAL("[mario-boot] SDK exports neither supported nn::init::Start ABI (4 or 5 arguments)\n");
    if (!dispatch_lookup(start))
        FATAL("[mario-boot] SDK Start %s at %llx has no recompiled entry\n", symbol, (unsigned long long)start);
    LOG("[mario-boot] SDK Start=%s address=%llx arguments=%d\n", symbol, (unsigned long long)start, finalizer ? 5 : 4);
    uint64_t ready = hle_register("<mario_rtld_ready>", modules_ready);
    uint64_t init = hle_register("<mario_rtld_init>", initialize_modules);
    uint64_t fini = finalizer ? hle_register("<mario_rtld_fini>", finalize_modules) : 0;
    KThread *thread = kernel_create_main_thread(start, stack_size, priority);
    // kernel_run_main sets x0..x3 and starts the host thread. Set x4 first.
    thread->cpu.x[4] = fini;
    LOG("[boot] executing first guest function\n");
    kernel_run_main(thread, thread->handle, 0, ready, init);
}
#endif
