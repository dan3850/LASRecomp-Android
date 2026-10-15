/* Harmless library included in the public APK to test loading read-only native code.
 * No game data is used, copied or transmitted by this diagnostic. */
#if defined(__GNUC__)
__attribute__((visibility("default")))
#endif
int lasrecomp_loader_probe(void) { return 0x4c4153; }
