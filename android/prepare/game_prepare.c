#include <jni.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "../../runtime/romfs_build.h"

/* This is the same RomFS image builder used by the desktop LASRecomp,
   embedded directly in the Android APK. It does not invoke a shell. */
static int exists_regular(const char *p) {
    struct stat st;
    return stat(p, &st) == 0 && S_ISREG(st.st_mode);
}
static int exists_directory(const char *p) {
    struct stat st;
    return stat(p, &st) == 0 && S_ISDIR(st.st_mode);
}
static int path_join(char *out, size_t n, const char *root, const char *tail) {
    int written = snprintf(out, n, "%s/%s", root, tail);
    return written > 0 && (size_t)written < n;
}

JNIEXPORT jstring JNICALL
Java_com_retroaura_lasrecomp_GameImportActivity_nativePrepareGame(
    JNIEnv *env, jclass cls, jstring stageDir) {
    (void)cls;
    if (!stageDir) return (*env)->NewStringUTF(env, "Pasta do jogo nao informada");
    const char *root = (*env)->GetStringUTFChars(env, stageDir, NULL);
    if (!root) return NULL;

    char main_path[4096], npdm_path[4096], sdk_path[4096];
    char region_path[4096], romfs_path[4096], image_path[4096];
    char error[384] = "";
    static const unsigned char wanted_id[8] = {0xae, 0x16, 0xf7, 0x1e, 0x00, 0x2a, 0xf8, 0xcb};

    if (root[0] != '/' ||
        !path_join(main_path, sizeof main_path, root, "exefs/main") ||
        !path_join(npdm_path, sizeof npdm_path, root, "exefs/main.npdm") ||
        !path_join(sdk_path, sizeof sdk_path, root, "exefs/sdk") ||
        !path_join(region_path, sizeof region_path, root, "romfs/region_common") ||
        !path_join(romfs_path, sizeof romfs_path, root, "romfs") ||
        !path_join(image_path, sizeof image_path, root, "romfs.bin")) {
        snprintf(error, sizeof error, "Caminho dos arquivos invalido");
        goto finish;
    }
    if (!exists_regular(main_path) || !exists_regular(npdm_path) ||
        !exists_regular(sdk_path) || !exists_directory(region_path)) {
        snprintf(error, sizeof error, "Arquivos incompletos: precisa de exefs/main, main.npdm, sdk e romfs/region_common");
        goto finish;
    }
    FILE *f = fopen(main_path, "rb");
    if (!f) {
        snprintf(error, sizeof error, "Nao consegui ler exefs/main");
        goto finish;
    }
    unsigned char got_id[8] = {0};
    int valid = fseek(f, 0x40, SEEK_SET) == 0 &&
                fread(got_id, 1, sizeof got_id, f) == sizeof got_id;
    fclose(f);
    if (!valid || memcmp(got_id, wanted_id, sizeof wanted_id)) {
        snprintf(error, sizeof error, "Versao do jogo incompativel: e necessario Link's Awakening v1.0.0, sem update");
        goto finish;
    }
    if (!romfs_build(romfs_path, image_path, NULL, error, sizeof error)) {
        if (!error[0]) snprintf(error, sizeof error, "Falha ao criar romfs.bin");
        goto finish;
    }
    if (!exists_regular(image_path)) {
        snprintf(error, sizeof error, "romfs.bin nao foi criado");
    }
finish:
    (*env)->ReleaseStringUTFChars(env, stageDir, root);
    if (!error[0]) return NULL; // success
    return (*env)->NewStringUTF(env, error);
}
