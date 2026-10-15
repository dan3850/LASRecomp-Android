/*
 * User-selected game-code compatibility diagnostic.
 * The APK never includes the player's Zelda code. This function receives a
 * read-only copy in app-private code_cache, checks ELF64 AArch64 and then
 * attempts dlopen with the real engine in the same Android linker namespace.
 * Importing executable code is an explicit, informed user action.
 */
#include <jni.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include "../../runtime/gamelib.h"

JNIEXPORT jstring JNICALL
Java_com_retroaura_lasrecomp_GameImportActivity_nativeValidateGameCode(
    JNIEnv *env, jclass cls, jstring libraryPath) {
    (void)cls;
    if (!libraryPath) return (*env)->NewStringUTF(env, "FALHOU: biblioteca ausente");
    const char *path = (*env)->GetStringUTFChars(env, libraryPath, NULL);
    if (!path) return NULL;
    char result[900] = "";
    void *engine = NULL, *game = NULL;
    struct stat st;
    unsigned char header[64] = {0};

    if (path[0] != '/' || lstat(path, &st) || !S_ISREG(st.st_mode) ||
        (st.st_mode & 0222) || st.st_size < 1024 * 1024 ||
        st.st_size > 512LL * 1024 * 1024) {
        snprintf(result, sizeof result,
                 "FALHOU: biblioteca deve ser arquivo privado, somente leitura (1 a 512 MB)");
        goto done;
    }
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        snprintf(result, sizeof result, "FALHOU: nao consegui ler a biblioteca");
        goto done;
    }
    size_t n = fread(header, 1, sizeof header, fp);
    fclose(fp);
    if (n != sizeof header || memcmp(header, "\177ELF", 4) ||
        header[4] != 2 || header[5] != 1 ||
        header[16] != 3 || header[17] != 0 ||
        header[18] != 183 || header[19] != 0) {
        snprintf(result, sizeof result, "FALHOU: nao e biblioteca ELF64 AArch64 Android");
        goto done;
    }

    /* This must happen before liblasgame.so: guest rt_*/ 
    /* and hle_* relocations resolve against the real runtime's exports. */
    engine = dlopen("liblasrecomp_runtime.so", RTLD_NOW | RTLD_GLOBAL);
    if (!engine) {
        const char *error = dlerror();
        snprintf(result, sizeof result, "FALHOU ao carregar motor Android: %.700s",
                 error ? error : "erro desconhecido");
        goto done;
    }
    game = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!game) {
        const char *error = dlerror();
        snprintf(result, sizeof result, "FALHOU ao carregar Zelda: %.700s",
                 error ? error : "erro desconhecido");
        goto done;
    }
    GameLibEntry entry = (GameLibEntry)(void *)dlsym(game, GAMELIB_ENTRY);
    if (!entry) {
        snprintf(result, sizeof result, "FALHOU: simbolo lasgame_tables ausente");
        goto done;
    }
    const GameLibTables *tables = entry();
    if (!tables || tables->abi != GAMELIB_ABI || !tables->id ||
        strcmp(tables->id, GAMELIB_ID) ||
        !tables->main_addrs || !tables->sdk_addrs ||
        !tables->main_fns || !tables->sdk_fns ||
        !tables->main_count || !tables->sdk_count) {
        snprintf(result, sizeof result,
                 "FALHOU: ABI, identificador ou tabelas do jogo incompativeis");
        goto done;
    }
    snprintf(result, sizeof result,
             "OK: liblasgame.so ARM64 carregada com o motor e tabelas ABI validadas. "
             "Isso ainda nao comprova que o Zelda inicia.");
done:
    if (game) dlclose(game);
    if (engine) dlclose(engine);
    (*env)->ReleaseStringUTFChars(env, libraryPath, path);
    return (*env)->NewStringUTF(env, result);
}
