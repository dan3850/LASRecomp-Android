// Observe the final default-registry candidate without modifying guest state.
static void mario_resource_string(uint64_t pointer, char *out, size_t capacity) {
    size_t i = 0;
    for (; i + 1 < capacity; i++) {
        char ch;
        if (!mario_debug_read(pointer + i, &ch, 1)) break;
        out[i] = ch;
        if (!ch) return;
    }
    out[i] = 0;
}

static void mario_resource_trace(Cpu *c) {
    // Exact call site verified against the generated Mario main code. Stop at
    // sixteen reports per thread; no per-frame resource logging is enabled.
    static __thread unsigned reports;
    if (c->x[30] != MAIN_BASE + 0x8a1a5c || reports >= 16) return;
    uint64_t manager = c->x[21], buffer, pointer, name, fallback;
    uint32_t count, capacity, head;
    if (!mario_debug_read(manager + 0x10, &count, 4) || !count || count > 64 ||
            c->x[23] + 1 != count) return;
    if (!mario_debug_read(manager, &buffer, 8) ||
            !mario_debug_read(manager + 8, &capacity, 4) ||
            !mario_debug_read(manager + 12, &head, 4) ||
            !capacity || capacity > 4096 || count > capacity || head >= capacity) return;
    reports++;
    char query[256] = "", default_name[256] = "Scene";
    if (mario_debug_read(c->x[20] + 8, &pointer, 8))
        mario_resource_string(pointer, query, sizeof query);
    if (mario_debug_read(manager + 0xb0, &fallback, 8) && fallback)
        mario_resource_string(fallback, default_name, sizeof default_name);
    LOG("[mario-resource] query=%s default=%s count=%u head=%u capacity=%u\n",
        query, default_name, count, head, capacity);
    for (uint32_t i = 0; i < count; i++) {
        uint32_t index = (head + i) % capacity;
        char label[256] = "";
        if (!mario_debug_read(buffer + index * 8ull, &pointer, 8)) break;
        if (pointer && mario_debug_read(pointer + 8, &name, 8))
            mario_resource_string(name, label, sizeof label);
        LOG("[mario-resource] slot=%u object=%llx name=%s\n", i,
            (unsigned long long)pointer, label);
    }
}
