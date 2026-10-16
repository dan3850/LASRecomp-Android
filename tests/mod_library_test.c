// Production JNI validation with fake linker handles, never executing game code.
#include <assert.h>
#include <dlfcn.h>
#include <jni.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void *test_open(const char *, int);
static void *test_symbol(void *, const char *);
static int test_close(void *);
static char *test_error(void);
#define dlopen test_open
#define dlsym test_symbol
#define dlclose test_close
#define dlerror test_error
#include "../android/prepare/private_game_code.c"

static int engine_fails, game_fails, cap_missing, opens, closes;
static uint64_t count = 1, addresses[] = {0x7000000000};
static void guest(Cpu *c) { (void)c; }
static GuestFn functions[] = {guest};
static GameLibTables table = {GAMELIB_ABI, GAMELIB_ID, addresses, addresses,
                             functions, functions, &count, &count};
static const char *cap = LAS_MOD_MENU_CAPABILITY;
static const GameLibTables *entry(void) { return &table; }
static const char *capability(void) { return cap; }
static void *test_open(const char *name, int flags) {
    (void)flags;
    ++opens;
    if (!strcmp(name, "liblasrecomp_runtime.so")) return engine_fails ? NULL : (void *)1;
    return game_fails ? NULL : (void *)2;
}
static void *test_symbol(void *handle, const char *name) {
    assert(handle == (void *)2);
    if (!strcmp(name, GAMELIB_ENTRY)) return (void *)entry;
    if (!strcmp(name, "lasgame_mod_menu_v1")) return cap_missing ? NULL : (void *)capability;
    return NULL;
}
static int test_close(void *handle) { assert(handle); ++closes; return 0; }
static char *test_error(void) { return "test missing dependency"; }
static const char *utf(JNIEnv *env, jstring text, jboolean *copy) {
    (void)env; (void)copy; return (const char *)text;
}
static void release(JNIEnv *env, jstring text, const char *chars) { (void)env; (void)text; (void)chars; }
static char message[1000];
static jstring string(JNIEnv *env, const char *text) {
    (void)env; snprintf(message, sizeof message, "%s", text); return (jstring)message;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const struct JNINativeInterface_ ops = {.GetStringUTFChars=utf, .ReleaseStringUTFChars=release, .NewStringUTF=string};
    JNIEnv env = &ops;
    const char *path = argv[1];
    unsigned char header[64] = {0x7f, 'E', 'L', 'F', 2, 1};
    header[16] = 3; header[18] = 183;
    FILE *file = fopen(path, "wb"); assert(file);
    assert(fwrite(header, 1, sizeof header, file) == sizeof header);
    assert(!fseek(file, 1024 * 1024 - 1, SEEK_SET)); assert(fputc(0, file) == 0); fclose(file);
    assert(!chmod(path, 0400));
#define SUPPORT() Java_com_retroaura_lasrecomp_GameImportActivity_nativeSupportsModMenu(&env, NULL, (jstring)path)
#define VALIDATE() Java_com_retroaura_lasrecomp_GameImportActivity_nativeValidateGameCode(&env, NULL, (jstring)path)
    assert(SUPPORT() == JNI_TRUE);
    assert(!strncmp((char *)VALIDATE(), "OK:", 3));
    cap_missing = 1; assert(SUPPORT() == JNI_FALSE); cap_missing = 0;
    cap = "other-mod"; assert(SUPPORT() == JNI_FALSE); cap = LAS_MOD_MENU_CAPABILITY;
    table.abi++; assert(SUPPORT() == JNI_FALSE); assert(strstr((char *)VALIDATE(), "FALHOU")); table.abi--;
    table.id = "other"; assert(SUPPORT() == JNI_FALSE); table.id = GAMELIB_ID;
    table.main_count = NULL; assert(SUPPORT() == JNI_FALSE); table.main_count = &count;
    count = 0; assert(SUPPORT() == JNI_FALSE); count = 1;
    engine_fails = 1; assert(SUPPORT() == JNI_FALSE); assert(strstr((char *)VALIDATE(), "FALHOU")); engine_fails = 0;
    game_fails = 1; assert(SUPPORT() == JNI_FALSE); assert(strstr((char *)VALIDATE(), "FALHOU")); game_fails = 0;
    assert(!chmod(path, 0600)); assert(strstr((char *)VALIDATE(), "somente leitura"));
    file = fopen(path, "r+b"); assert(file); assert(!fseek(file, 18, SEEK_SET)); fputc(62, file); fclose(file);
    assert(!chmod(path, 0400)); assert(strstr((char *)VALIDATE(), "ELF64 AArch64"));
    assert(opens > closes); // failure cases don't return a handle to close
    unlink(path);
    puts("JNI compatibility/validation: old module, wrong capability/ABI, missing dependency, permissions and architecture PASS");
}
