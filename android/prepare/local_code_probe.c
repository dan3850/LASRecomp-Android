/*
 * Feasibility probe for an in-app recompiler on Android.
 *
 * Copies ONLY our own small, signed-APK test library to app-private cache,
 * makes that copy read-only, and verifies dlopen/dlsym. It deliberately does
 * not load Zelda code, execute a compiler, or relax APK security settings.
 * A successful probe is necessary but NOT sufficient to prove future game
 * code loading (the real .so is much larger and has runtime dependencies).
 */
#include <jni.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif

static int copy_readonly(const char *source, const char *destination,
                         char *why, size_t why_size) {
    int src = open(source, O_RDONLY | O_CLOEXEC);
    if (src < 0) {
        snprintf(why, why_size, "Nao foi possivel abrir a biblioteca de teste: %s", strerror(errno));
        return 0;
    }
    int dst = open(destination, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (dst < 0) {
        snprintf(why, why_size, "Nao foi possivel criar arquivo privado: %s", strerror(errno));
        close(src);
        return 0;
    }
    int success = 1;
    char buffer[65536];
    for (;;) {
        ssize_t n = read(src, buffer, sizeof buffer);
        if (n == 0) break;
        if (n < 0) {
            if (errno == EINTR) continue;
            snprintf(why, why_size, "Falha ao ler biblioteca de teste: %s", strerror(errno));
            success = 0; break;
        }
        ssize_t offset = 0;
        while (offset < n) {
            ssize_t w = write(dst, buffer + offset, (size_t)(n - offset));
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) {
                snprintf(why, why_size, "Falha ao copiar biblioteca de teste: %s", strerror(errno));
                success = 0; break;
            }
            offset += w;
        }
        if (!success) break;
    }
    if (success && fchmod(dst, 0400) != 0) {
        snprintf(why, why_size, "Nao foi possivel tornar a biblioteca somente leitura: %s", strerror(errno));
        success = 0;
    }
    if (close(dst) != 0 && success) {
        snprintf(why, why_size, "Falha ao fechar arquivo privado: %s", strerror(errno));
        success = 0;
    }
    close(src);
    if (!success) unlink(destination);
    return success;
}

JNIEXPORT jstring JNICALL
Java_com_retroaura_lasrecomp_GameImportActivity_nativeProbeLocalCode(
    JNIEnv *env, jclass cls, jstring source, jstring cacheDirectory) {
    (void)cls;
    if (!source || !cacheDirectory)
        return (*env)->NewStringUTF(env, "FALHOU: caminho de teste ausente");
    const char *src = (*env)->GetStringUTFChars(env, source, NULL);
    if (!src) return NULL;
    const char *cache = (*env)->GetStringUTFChars(env, cacheDirectory, NULL);
    if (!cache) {
        (*env)->ReleaseStringUTFChars(env, source, src);
        return NULL;
    }
    char path[4096];
    char result[700] = "";
    size_t n = strlen(src);
    const char *expected = "/liblasrecomp_probe.so";
    if (n < strlen(expected) || strcmp(src + n - strlen(expected), expected) ||
        cache[0] != '/' ||
        snprintf(path, sizeof path, "%s/local-code-probe-%ld.so", cache, (long)getpid()) >= (int)sizeof path) {
        snprintf(result, sizeof result, "FALHOU: caminho de teste invalido");
    } else {
        // Recovery from an interrupted test: only our uniquely named scratch file.
        unlink(path);
        if (copy_readonly(src, path, result, sizeof result)) {
            void *handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
            if (!handle) {
                const char *reason = dlerror();
                snprintf(result, sizeof result, "FALHOU: Android recusou dlopen privado: %.540s",
                         reason ? reason : "erro desconhecido");
            } else {
                int (*entry)(void) = (int (*)(void))dlsym(handle, "lasrecomp_loader_probe");
                if (!entry || entry() != 0x4c4153)
                    snprintf(result, sizeof result, "FALHOU: biblioteca nao executou a funcao de teste");
                else
                    snprintf(result, sizeof result,
                             "OK: Android carregou uma .so privada somente leitura sem reinstalar o APK. "
                             "Isso nao garante que a biblioteca grande do jogo funcionara.");
                dlclose(handle);
            }
            unlink(path);
        } else if (result[0] != 'F') {
            char reason[600];
            snprintf(reason, sizeof reason, "%s", result);
            snprintf(result, sizeof result, "FALHOU: %.570s", reason);
        }
    }
    (*env)->ReleaseStringUTFChars(env, cacheDirectory, cache);
    (*env)->ReleaseStringUTFChars(env, source, src);
    return (*env)->NewStringUTF(env, result);
}
