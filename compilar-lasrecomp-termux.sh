#!/data/data/com.termux/files/usr/bin/bash
# LASRecomp-Android / Termux arm64; build incremental, sem clean.
# Nao chama tools/build-android-termux.sh nem executa NDK Linux x86_64.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
CACHE="${LASRECOMP_CACHE:-$HOME/.cache/lasrecomp-termux}"
OUT="$ROOT/build/termux-native"
DEPS="$CACHE/src"
WORK="$CACHE/build"
JOBS="${LASRECOMP_JOBS:-3}"
mkdir -p "$OUT" "$DEPS" "$WORK"
exec > >(tee -a "$OUT/compilacao.log") 2>&1
fail(){ echo "ERRO: $*" >&2; exit 1; }
step(){ printf '\n== %s ==\n' "$*"; }
[[ "$(uname -m)" == aarch64 && "$PREFIX" == /data/data/com.termux/files/usr ]] || fail "Execute no Termux ARM64, fora de proot."
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || fail "LASRECOMP_JOBS invalido"
# Ferramentas do SDK podem existir sem comandos no PATH.
# Nao tente instalar nomes de pacotes inexistentes no Termux.
for cmd in git clang clang++ cmake ninja make llvm-ar llvm-nm llvm-readelf llvm-ranlib llvm-strip python3 java javac jar keytool aapt2 zip patchelf; do
 command -v "$cmd" >/dev/null 2>&1 || fail "Ferramenta ausente: $cmd. Instale apenas a dependencia correspondente."
done
if ! python3 -c 'import fontTools' >/dev/null 2>&1; then
 echo "Instalando modulo fonttools com pip (nao e pacote apt)..."
 python3 -m pip install --user fonttools || fail "Instale fonttools com python3 -m pip install fonttools"
fi
ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$PREFIX/opt/android-sdk}}"
[[ -d "$ANDROID_HOME/platforms" ]] || ANDROID_HOME="$HOME/android-sdk"
ANDROID_JAR="${ANDROID_JAR:-$(find "$ANDROID_HOME/platforms" -name android.jar -type f 2>/dev/null | sort -V | tail -1 || true)}"
[[ -s "$ANDROID_JAR" ]] || fail "SDK android.jar ausente. Configure ANDROID_HOME."
# D8 e um compilador Java: pode existir como comando ou dentro de d8.jar
# das Android SDK Build Tools. Nao precisa reinstalar o SDK nem instalar
# um pacote Termux chamado "d8".
D8_CMD=()
if [[ -n "${LASRECOMP_D8_JAR:-}" ]]; then
 [[ -s "$LASRECOMP_D8_JAR" ]] || fail "LASRECOMP_D8_JAR nao existe: $LASRECOMP_D8_JAR"
 D8_CMD=(java -Xmx1g -cp "$LASRECOMP_D8_JAR" com.android.tools.r8.D8)
elif command -v d8 >/dev/null 2>&1; then
 D8_CMD=(d8)
else
 D8_JAR="$(find "$ANDROID_HOME/build-tools" "$PREFIX/share/java" "$HOME/.gradle/caches/modules-2/files-2.1/com.android.tools/r8" \
   -type f \( -name d8.jar -o -name 'r8-*.jar' \) 2>/dev/null | sort -V | tail -n 1 || true)"
 if [[ -n "$D8_JAR" && -s "$D8_JAR" ]]; then
  D8_CMD=(java -Xmx1g -cp "$D8_JAR" com.android.tools.r8.D8)
 else
  fail "D8 nao encontrado. Procure d8.jar no SDK existente (build-tools/*/lib/d8.jar); configure LASRECOMP_D8_JAR=/caminho/d8.jar. Nao reinstale o SDK."
 fi
fi
echo "D8: ${D8_CMD[*]}"
# Reutiliza zipalign e apksigner do Android SDK quando nao estao no PATH.
find_sdk_tool(){
 local tool="$1" candidate
 if command -v "$tool" >/dev/null 2>&1; then command -v "$tool"; return; fi
 candidate="$(find "$ANDROID_HOME/build-tools" -type f -name "$tool" 2>/dev/null | sort -V | tail -1 || true)"
 [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return; }
 return 1
}
# SDK zipalign costuma ser ELF x86_64 e nao executa em Termux ARM64.
# Aceita somente zipalign instalado nativamente no PATH.
ZIPALIGN_CMD="$(command -v zipalign || true)"
APKSIGNER_CMD="$(find_sdk_tool apksigner || true)"
if [[ -z "$ZIPALIGN_CMD" ]]; then
 echo "AVISO: zipalign nao existe como executavel ARM64; empacotamento prosseguira sem ele."
fi
if [[ -z "$APKSIGNER_CMD" ]]; then
 APKSIGNER_JAR="$(find "$ANDROID_HOME/build-tools" -type f -name apksigner.jar 2>/dev/null | sort -V | tail -1 || true)"
 [[ -n "$APKSIGNER_JAR" ]] || fail "apksigner nao encontrado no SDK; falta build-tools com apksigner.jar"
 APKSIGNER_CMD="java -jar $APKSIGNER_JAR"
fi

step "Projeto LASRecomp (branch intacta, sem git reset/pull/clean)"
git -C "$ROOT" log -1 --oneline || true
checkout(){
 local name="$1" url="$2" tag="$3" dest="$DEPS/$1"
 if [[ ! -d "$dest/.git" ]]; then
  step "Obtendo $name $tag (uma vez)"
  git clone -q --depth 1 --branch "$tag" "$url" "$dest"
 fi
 [[ -d "$dest/.git" ]] || fail "Cache incompleto: $dest"
}
pin(){
 local name="$1" url="$2" sha="$3" dest="$4"
 if [[ ! -d "$dest/.git" ]]; then
  mkdir -p "$dest"
  git -C "$dest" init -q
  git -C "$dest" remote add origin "$url"
  git -C "$dest" fetch -q --depth=1 origin "$sha"
  git -C "$dest" checkout -q --detach FETCH_HEAD
 fi
 [[ "$(git -C "$dest" rev-parse HEAD)" == "$sha" ]] || fail "Revisao errada: $name"
}
checkout sdl3 https://github.com/libsdl-org/SDL.git release-3.2.22
checkout shaderc https://github.com/google/shaderc.git v2024.4
checkout volk https://github.com/zeux/volk.git 1.3.295
checkout vma https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator.git v3.1.0
checkout ffmpeg https://github.com/FFmpeg/FFmpeg.git n7.1.1
pin glslang https://github.com/KhronosGroup/glslang.git a0995c49ebcaca2c6d3b03efbabf74f3843decdb "$DEPS/shaderc/third_party/glslang"
pin spirv-headers https://github.com/KhronosGroup/SPIRV-Headers.git 3f17b2af6784bfa2c5aa5dbb8e0e74a607dd8b3b "$DEPS/shaderc/third_party/spirv-headers"
pin spirv-tools https://github.com/KhronosGroup/SPIRV-Tools.git 4d2f0b40bfe290dea6c6904dafdf7fd8328ba346 "$DEPS/shaderc/third_party/spirv-tools"
cd "$ROOT"
# Clang do Termux e Android/Bionic; bibliotecas sao validadas antes do APK.
CMAKE_OPTS=(-G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang
 -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_FLAGS=-fPIC -DCMAKE_CXX_FLAGS=-fPIC
 -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384")
# SDL 3.2.22 espera cpu-features.c em CMAKE_ANDROID_NDK/sources/android.
# No Termux, clang ja mira Android, mas CMAKE_ANDROID_NDK fica vazio.
# Usa uma arvore de compatibilidade isolada, sem modificar SDK ou fontes SDL.
SDL_NDK_COMPAT="$WORK/sdl-ndk-compat"
SDL_CPUFEATURES="$SDL_NDK_COMPAT/sources/android/cpufeatures"
mkdir -p "$SDL_CPUFEATURES"
if [[ ! -s "$SDL_CPUFEATURES/cpu-features.c" ]]; then
 CPU_SRC="$(find "$ANDROID_HOME/ndk" "$DEPS/sdl3" "$PREFIX" -type f -name cpu-features.c 2>/dev/null | head -n 1 || true)"
 [[ -n "$CPU_SRC" ]] || fail "SDL3 precisa de cpu-features.c; nao encontrado no NDK, SDL3 ou Termux. Nao vou criar stub falso."
 cp "$CPU_SRC" "$SDL_CPUFEATURES/cpu-features.c"
 CPU_HEADER="$(dirname "$CPU_SRC")/cpu-features.h"
 [[ -f "$CPU_HEADER" ]] && cp "$CPU_HEADER" "$SDL_CPUFEATURES/cpu-features.h"
fi
CMAKE_OPTS+=("-DCMAKE_ANDROID_NDK=$SDL_NDK_COMPAT")
step "SDL3 — compila do fonte"
# O CMake anterior persistiu ANDROID=ON no cache do SDL3.
# Limpa apenas a entrada obsoleta, sem remover objetos ou caches de outras libs.
if [[ -f "$WORK/sdl3/CMakeCache.txt" ]]; then
 sed -i '/^ANDROID:UNINITIALIZED=/d; /^ANDROID:BOOL=/d; /^SDL_ANDROID:UNINITIALIZED=/d' "$WORK/sdl3/CMakeCache.txt"
fi
cmake -S "$DEPS/sdl3" -B "$WORK/sdl3" "${CMAKE_OPTS[@]}" \
 -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TEST_LIBRARY=OFF \
 -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF -DSDL_OPENGLES=OFF -DSDL_OPENGLES2=OFF -DSDL_OPENGL=OFF
cmake --build "$WORK/sdl3" --parallel "$JOBS"
SDL_SO="$(find "$WORK/sdl3" -name libSDL3.so -type f -print -quit)"
[[ -s "$SDL_SO" ]] || fail "SDL3 nao gerou libSDL3.so"
SDL_HEADERS="$DEPS/sdl3/include"
SDL_JAVA="$DEPS/sdl3/android-project/app/src/main/java"
step "Shaderc — compila do fonte"
python3 - "$DEPS/shaderc" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
edits = [
 (p / 'third_party/CMakeLists.txt',
  'set(GLSLANG_ENABLE_INSTALL $<NOT:${SKIP_GLSLANG_INSTALL}>)',
  'set(GLSLANG_ENABLE_INSTALL OFF)'),
 (p / 'libshaderc/CMakeLists.txt',
  'set_target_properties(shaderc_shared PROPERTIES SOVERSION 1)', '')
]
for path, old, new in edits:
    src = path.read_text()
    if old in src:
        path.write_text(src.replace(old, new))
    elif new and new not in src:
        raise SystemExit(f'Configuração não reconhecida: {path}')
PY
cmake -S "$DEPS/shaderc" -B "$WORK/shaderc" "${CMAKE_OPTS[@]}" \
 -DSHADERC_SKIP_TESTS=ON -DSHADERC_SKIP_EXAMPLES=ON \
 -DSHADERC_SKIP_COPYRIGHT_CHECK=ON -DSHADERC_SKIP_INSTALL=ON \
 -DSPIRV_SKIP_EXECUTABLES=ON -DENABLE_GLSLANG_BINARIES=OFF \
 -DSHADERC_ENABLE_WGSL_OUTPUT=OFF
cmake --build "$WORK/shaderc" --target shaderc_shared --parallel "$JOBS"
SHADERC_SO="$(find "$WORK/shaderc" -name libshaderc_shared.so -type f -print -quit)"
[[ -s "$SHADERC_SO" ]] || fail "Shaderc nao gerou libshaderc_shared.so"
# FFmpeg ARM64: assembler NEON gera relocacoes nao-PIC em libavutil.a.
# Compila apenas o FFmpeg com assembler desativado; nao toca no motor.
FFMPEG_PIC_STAMP="$WORK/ffmpeg-pic-noasm.stamp"
if [[ ! -f "$FFMPEG_PIC_STAMP" ]]; then
 if [[ -f "$DEPS/ffmpeg/ffbuild/config.mak" ]]; then
  make -C "$DEPS/ffmpeg" distclean || fail "Falhou ao reconfigurar somente FFmpeg"
 fi
 touch "$FFMPEG_PIC_STAMP"
fi
step "FFmpeg estatico ARM64"
FFDEST="$WORK/ffmpeg-install"
mkdir -p "$FFDEST"
if [[ ! -s "$DEPS/ffmpeg/ffbuild/config.mak" ]]; then
 (cd "$DEPS/ffmpeg" && ./configure --prefix="$FFDEST" --target-os=android \
   --arch=aarch64 --cpu=armv8-a --cc=clang --cxx=clang++ \
   --ar=llvm-ar --nm=llvm-nm --ranlib=llvm-ranlib --strip=llvm-strip \
   --enable-pic --disable-asm --disable-doc --disable-programs --enable-static \
   --disable-shared --disable-debug --disable-autodetect --disable-network \
   --disable-everything --enable-avcodec --enable-avformat --enable-avutil \
   --enable-swscale --enable-swresample \
   --enable-decoder=aac,h264,hevc,vp8,vp9,vorbis,opus,mp3 \
   --enable-parser=aac,h264,hevc,vp8,vp9,vorbis,opus \
   --enable-demuxer=mov,matroska,ogg,mpegts \
   --enable-protocol=file --extra-cflags="-fPIC")
fi
make -C "$DEPS/ffmpeg" -j"$JOBS"
make -C "$DEPS/ffmpeg" install
for a in avformat avcodec avutil swscale swresample; do
 [[ -s "$FFDEST/lib/lib$a.a" ]] || fail "Faltou FFmpeg lib$a.a"
done
OBJ="$OUT/obj"; LIB="$OUT/lib"
mkdir -p "$OBJ" "$LIB"
STAMP="$OUT/flags.stamp"
HASH="$(sha256sum "$0" | cut -d' ' -f1)"
if [[ ! -f "$OUT/flags.id" || "$(cat "$OUT/flags.id")" != "$HASH" ]]; then
 printf '%s' "$HASH" > "$OUT/flags.id"; touch "$STAMP"
fi
compile(){
 local src="$1" obj="$2" compiler="$3"; shift 3
 local dep="$obj.d"
 mkdir -p "$(dirname "$obj")"
 # Include dependencies matter for shared struct layouts (e.g. TexBackend).
 # Old objects without a depfile are rebuilt once; private game-code objects
 # belong to another script and remain untouched.
 if [[ ! -s "$obj" || ! -s "$dep" || "$src" -nt "$obj" || "$STAMP" -nt "$obj" ]] ||
    ! make -q -f "$dep" "$obj" 2>/dev/null; then
  echo "CC ${src#"$ROOT"/}"
  "$compiler" -O2 -fPIC -fno-strict-aliasing \
   -Wno-nullability-completeness -MMD -MP -MF "$dep.tmp" -MQ "$obj" \
   "$@" -c "$src" -o "$obj.tmp"
  mv -f "$dep.tmp" "$dep"
  mv -f "$obj.tmp" "$obj"
 fi
}
cd "$ROOT"
step "Compilando engine C da branch"
CORE=()
while IFS= read -r src; do
 case "$src" in */hle/movie.c|*/nvn/smaa_data.c) continue;; esac
 obj="$OBJ/core/${src#"$ROOT"/}.o"
 compile "$src" "$obj" clang -std=gnu11 -Iruntime -Iruntime/nvn \
  -I"$SDL_HEADERS" -Wno-format -Werror=implicit-function-declaration
 CORE+=("$obj")
done < <(find "$ROOT/runtime" "$ROOT/runtime/hle" "$ROOT/runtime/services" \
 "$ROOT/runtime/nvn" "$ROOT/runtime/nvn/maxwell" -maxdepth 1 \
 -type f -name '*.c' | sort -u; echo "$ROOT/runtime/platform/android.c")
compile "$ROOT/runtime/hle/movie.c" "$OBJ/core/hle/movie.c.o" clang \
 -std=gnu11 -Iruntime -I"$SDL_HEADERS" -I"$FFDEST/include" \
 -Werror=implicit-function-declaration
CORE+=("$OBJ/core/hle/movie.c.o")
llvm-ar rcs "$LIB/liblasrecomp-core.a" "${CORE[@]}"
# Localiza headers Vulkan existentes (Termux, NDK ou dependencias).
VULKAN_INCLUDE=""
for candidate in "$PREFIX/include" "$ANDROID_HOME/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/include" "$DEPS/vma/include" "$DEPS/volk"; do
 if [[ -f "$candidate/vulkan/vulkan.h" ]]; then VULKAN_INCLUDE="$candidate"; break; fi
done
if [[ -z "$VULKAN_INCLUDE" ]]; then
 VULKAN_HEADER="$(find "$ANDROID_HOME/ndk" "$DEPS" -type f -path '*/vulkan/vulkan.h' -print -quit 2>/dev/null || true)"
 [[ -n "$VULKAN_HEADER" ]] || fail "Headers Vulkan ausentes. Instale pkg install vulkan-headers (se disponivel) ou configure LASRECOMP_VULKAN_INCLUDE."
 VULKAN_INCLUDE="${VULKAN_HEADER%/vulkan/vulkan.h}"
fi
[[ -z "${LASRECOMP_VULKAN_INCLUDE:-}" ]] || VULKAN_INCLUDE="$LASRECOMP_VULKAN_INCLUDE"
[[ -f "$VULKAN_INCLUDE/vulkan/vulkan.h" ]] || fail "vulkan/vulkan.h ausente em $VULKAN_INCLUDE"
echo "Vulkan headers: $VULKAN_INCLUDE"
step "Compilando Vulkan/ImGui"
mkdir -p "$OBJ/inc"
python3 tools/vulkan-cache-build-id.py --output "$OBJ/inc/vulkan_cache_build_id.h"
LC_ALL=C tr -d '\r' < third_party/smaa/SMAA.hlsl \
 | LC_ALL=C tr '\200-\377' '?' \
 | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/^/"/' -e 's/$/\\n"/' \
 > "$OBJ/inc/smaa_hlsl.inc"
INC=(-idirafter "$VULKAN_INCLUDE" -Iruntime -Iruntime/nvn -Ithird_party/imgui \
 -Ithird_party/imgui/backends -Ithird_party/smaa/Textures \
 -I"$SDL_HEADERS" -I"$DEPS/shaderc/libshaderc/include" \
 -I"$DEPS/vma/include" -I"$DEPS/volk" -I"$OBJ/inc")
RENDER=()
while IFS= read -r src; do
 obj="$OBJ/renderer/${src#"$ROOT"/}.o"
 cc=clang; std=-std=gnu11
 [[ "$src" == *.cpp ]] && { cc=clang++; std=-std=c++17; }
 compile "$src" "$obj" "$cc" "$std" -DVK_NO_PROTOTYPES \
  "-DLASRECOMP_BUILD_SHA=\"$(git -C "$ROOT" rev-parse --short=12 HEAD)\"" \
  -DIMGUI_IMPL_VULKAN_USE_VOLK -D_FILE_OFFSET_BITS=64 "${INC[@]}"
 RENDER+=("$obj")
done < <(
 find "$ROOT/runtime/nvn/vulkan" -maxdepth 1 -type f \
  \( -name '*.c' -o -name '*.cpp' \) | sort
 for p in imgui.cpp imgui_draw.cpp imgui_tables.cpp imgui_widgets.cpp; do
  echo "$ROOT/third_party/imgui/$p"
 done
 for p in imgui_impl_sdl3.cpp imgui_impl_vulkan.cpp; do
  echo "$ROOT/third_party/imgui/backends/$p"
 done
 echo "$ROOT/runtime/nvn/smaa_data.c"
 echo "$ROOT/android/game/png_writer.c"
 echo "$DEPS/volk/volk.c"
)
llvm-ar rcs "$LIB/liblasrecomp-renderer.a" "${RENDER[@]}"
step "Compilando UI C++ e liblasrecomp_runtime.so"
UI=()
for src in "$ROOT"/runtime/ui/*.mm; do
 obj="$OBJ/ui/$(basename "$src").o"
 compile "$src" "$obj" clang++ -x c++ -std=c++17 \
  -DVK_NO_PROTOTYPES -DIMGUI_IMPL_VULKAN_USE_VOLK \
  -idirafter "$VULKAN_INCLUDE" -Iruntime -Iruntime/nvn -Iruntime/ui -Ithird_party/imgui \
  -Ithird_party/imgui/backends -I"$SDL_HEADERS" \
  -I"$FFDEST/include" -I"$DEPS/vma/include" -I"$DEPS/volk"
 UI+=("$obj")
done
RUNTIME="$LIB/liblasrecomp_runtime.so"
# Bionic's relocation group uses ELF DF_1_GLOBAL, not just dlopen's
# RTLD_GLOBAL. The separate importer and game modules need these exports.
clang++ -shared -Wl,-z,max-page-size=16384 -Wl,--no-undefined \
 -Wl,-z,global \
 -Wl,-soname,liblasrecomp_runtime.so -o "$RUNTIME.tmp" "${UI[@]}" \
 -Wl,--whole-archive "$LIB/liblasrecomp-core.a" \
 "$LIB/liblasrecomp-renderer.a" -Wl,--no-whole-archive \
 -L"$(dirname "$SDL_SO")" -L"$(dirname "$SHADERC_SO")" \
 -lSDL3 -lshaderc_shared -Wl,--start-group \
 "$FFDEST/lib/libavformat.a" "$FFDEST/lib/libavcodec.a" \
 "$FFDEST/lib/libavutil.a" "$FFDEST/lib/libswscale.a" \
 "$FFDEST/lib/libswresample.a" -Wl,--end-group -llog -landroid -ldl -lz -lm
llvm-readelf -d "$RUNTIME.tmp" | grep -E 'FLAGS_1.*GLOBAL' >/dev/null ||
 fail "Motor sem DF_1_GLOBAL: a biblioteca do jogo nao resolveria os simbolos no Android."
RUNTIME_EXPORTS="$(llvm-nm -D --defined-only "$RUNTIME.tmp")"
for symbol in g_fnprof fnprof_hit rt_mod_nop; do
 grep -Eq "[[:space:]]$symbol$" <<< "$RUNTIME_EXPORTS" ||
  fail "Motor nao exporta $symbol; APK nao sera empacotado."
done
mv -f "$RUNTIME.tmp" "$RUNTIME"
step "Compilando SDL_main e bibliotecas do app"
clang -shared -fPIC -O2 -Wl,-z,max-page-size=16384 \
 -Wl,-soname,libmain.so -I"$SDL_HEADERS" -L"$(dirname "$SDL_SO")" \
 -o "$LIB/libmain.so" android/game/game_entry.c -lSDL3 -ldl -llog
clang -shared -fPIC -O2 -fvisibility=hidden -Wl,-z,max-page-size=16384 \
 -Wl,-soname,liblasrecomp_prepare.so -o "$LIB/liblasrecomp_prepare.so" \
 android/prepare/game_prepare.c android/prepare/local_code_probe.c \
 android/prepare/private_game_code.c runtime/romfs_build.c -llog -ldl
clang -shared -fPIC -O2 -fvisibility=hidden -Wl,-z,max-page-size=16384 \
 -Wl,-soname,liblasrecomp_probe.so -o "$LIB/liblasrecomp_probe.so" \
 android/prepare/loader_probe_module.c
# AdrenoTools is BSD-2-Clause, unlike Eden's GPL user interface.
# Build once in the Termux cache and reuse CMake/Ninja outputs afterwards.
step "AdrenoTools - Vulkan personalizado ARM64"
ADRENO_SRC="$DEPS/libadrenotools"
if [[ ! -d "$ADRENO_SRC/.git" ]]; then
 git clone -q --depth 1 --recurse-submodules https://github.com/bylaws/libadrenotools.git "$ADRENO_SRC"
fi
[[ -f "$ADRENO_SRC/lib/linkernsbypass/CMakeLists.txt" ]] ||
 (cd "$ADRENO_SRC" && git submodule update --init --recursive)
ADRENO_BUILD="$WORK/adrenotools"
# Avoid false failures from grep -q/pipefail, and check real ELF machine type.
is_arm64_so() {
 local header
 header="$(llvm-readelf -h "$1" 2>/dev/null)" || return 1
 [[ "$header" == *AArch64* ]]
}
build_adrenotools() {
 cmake -S "$ADRENO_SRC" -B "$ADRENO_BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_ANDROID_ARCH_ABI=arm64-v8a -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=ON
 cmake --build "$ADRENO_BUILD" --parallel "$JOBS"
}
adrenotools_arm64_ok() {
 local name source_so
 for name in libadrenotools.so libmain_hook.so libhook_impl.so libfile_redirect_hook.so libgsl_alloc_hook.so; do
  source_so="$(find "$ADRENO_BUILD" -type f -name "$name" -print -quit)"
  if [[ -z "$source_so" || ! -s "$source_so" ]]; then
   echo "AdrenoTools: biblioteca ausente: $name" >&2
   return 1
  fi
  if ! is_arm64_so "$source_so"; then
   echo "AdrenoTools: biblioteca com arquitetura inválida: $source_so" >&2
   llvm-readelf -h "$source_so" 2>&1 | grep -E 'Class:|Machine:' || true
   return 1
  fi
 done
}
build_adrenotools
if ! adrenotools_arm64_ok; then
 # Repair ONLY this isolated cache; keep FFmpeg/SDL/shaderc and game-code objects.
 step "Regerando apenas AdrenoTools ARM64 (cache antigo/incompatível)"
 [[ "$ADRENO_BUILD" == "$WORK/adrenotools" ]] || fail "Pasta de build AdrenoTools inesperada"
 rm -rf -- "$ADRENO_BUILD"
 build_adrenotools
 adrenotools_arm64_ok || fail "AdrenoTools continua sem bibliotecas ARM64; confira clang -dumpmachine"
fi

step "Empacotando APK novo (sem modificar motor)"
STAGE="$OUT/stage"
# Apaga somente o staging temporario do APK; nunca caches, fontes ou objetos.
# Evita que uma liblasgame.so privada de uma rodada anterior vaze no APK atual.
rm -rf -- "$STAGE"
mkdir -p "$STAGE/lib/arm64-v8a" "$STAGE/assets" "$STAGE/dex" "$STAGE/classes"
# Hooks must be extracted to Android nativeLibraryDir (manifest extractNativeLibs=true).
for name in libadrenotools.so libmain_hook.so libhook_impl.so libfile_redirect_hook.so libgsl_alloc_hook.so; do
 source_so="$(find "$ADRENO_BUILD" -type f -name "$name" -print -quit)"
 cp -L "$source_so" "$STAGE/lib/arm64-v8a/$name"
done
for so in "$SDL_SO" "$SHADERC_SO" "$RUNTIME" "$LIB/libmain.so" \
 "$LIB/liblasrecomp_prepare.so" "$LIB/liblasrecomp_probe.so"; do
 cp -L "$so" "$STAGE/lib/arm64-v8a/$(basename "$so")"
done
# SDL3 compilado no Termux pode depender de libiconv.
# Empacota a biblioteca existente e preserva os objetos ja compilados.
if llvm-readelf -d "$SDL_SO" | grep -q 'Shared library: \[libiconv.so\]'; then
 ICONV_SO="$PREFIX/lib/libiconv.so"
 [[ -s "$ICONV_SO" ]] || fail "SDL3 requer libiconv.so, mas nao existe em $ICONV_SO (pkg install libiconv)"
 cp -L "$ICONV_SO" "$STAGE/lib/arm64-v8a/libiconv.so"
fi
if [[ -n "${LASRECOMP_GAME_SO:-}" ]]; then
 [[ -s "$LASRECOMP_GAME_SO" ]] || fail "LASRECOMP_GAME_SO ausente"
 llvm-nm -D --defined-only "$LASRECOMP_GAME_SO" \
  | grep -Eq '[[:space:]]lasgame_tables$' || fail "lasgame_tables ausente"
 cp -L "$LASRECOMP_GAME_SO" "$STAGE/lib/arm64-v8a/liblasgame.so"
fi
NDK="${ANDROID_NDK_HOME:-}"
if [[ -z "$NDK" ]]; then
 NDK="$(find "$ANDROID_HOME/ndk" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V | tail -1 || true)"
fi
[[ -d "$NDK" ]] || fail "NDK do Android nao encontrado (necessario apenas libc++_shared.so; nao executa binarios x86)."
CXX_SHARED="$(find "$NDK/toolchains/llvm/prebuilt" -type f -path '*/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so' -print -quit)"
[[ -s "$CXX_SHARED" ]] || fail "libc++_shared.so ausente no NDK"
cp "$CXX_SHARED" "$STAGE/lib/arm64-v8a/libc++_shared.so"
python3 tools/android-font-fallback.py \
 third_party/imgui/misc/fonts/Roboto-Medium.ttf "$STAGE/assets/lasrecomp_font.ttf"
mapfile -d '' -t SDLJAVA < <(find "$SDL_JAVA" -type f -name '*.java' -print0)
(( ${#SDLJAVA[@]} > 0 )) || fail "SDL Java nao encontrado"
# Optional original RadialGamePad. Explicit local dependencies only; no download.
RADIAL_AAR="${LASRECOMP_RADIAL_AAR:-}"
RADIAL_DEPS="${LASRECOMP_RADIAL_DEPS_DIR:-}"
RADIAL_JARS=()
RADIAL_CP="$ANDROID_JAR"
if [[ -n "$RADIAL_AAR" ]]; then
 [[ -s "$RADIAL_AAR" ]] || fail "RadialGamePad AAR nao encontrado: $RADIAL_AAR"
 [[ -d "$RADIAL_DEPS" ]] || fail "Configure LASRECOMP_RADIAL_DEPS_DIR com os JAR/AAR Kotlin, coroutines e AndroidX"
 mkdir -p "$STAGE/radial"
 unzip -p "$RADIAL_AAR" classes.jar > "$STAGE/radial/radial-classes.jar" || fail "AAR invalido"
 [[ -s "$STAGE/radial/radial-classes.jar" ]] || fail "AAR sem classes.jar"
 RADIAL_JARS+=("$STAGE/radial/radial-classes.jar")
 RADIAL_CP="$RADIAL_CP:$STAGE/radial/radial-classes.jar"
 # Android resources in an AAR cannot be linked by the current manifest-only aapt2 call.
 # Refuse silent packaging of a resource-dependent AAR until resource merging exists.
 if unzip -Z1 "$RADIAL_AAR" | grep -qE "^(res/|R.txt$)"; then
  fail "RadialGamePad AAR contem recursos Android: integrar compilacao aapt2 de recursos antes de ativar"
 fi
 mapfile -d '' -t RADIAL_DEP_FILES < <(find "$RADIAL_DEPS" -maxdepth 1 -type f \( -name '*.jar' -o -name '*.aar' \) -print0 | sort -z)
 (( ${#RADIAL_DEP_FILES[@]} > 0 )) || fail "Diretorio de dependencias RadialGamePad vazio"
 index=0
 for dep in "${RADIAL_DEP_FILES[@]}"; do
  if [[ "$dep" == *.aar ]]; then
   index=$((index+1))
   extracted="$STAGE/radial/dep-$index.jar"
   unzip -p "$dep" classes.jar > "$extracted" || fail "AAR de dependencia invalido: $dep"
   [[ -s "$extracted" ]] || fail "AAR sem classes.jar: $dep"
   RADIAL_JARS+=("$extracted")
  else
   RADIAL_JARS+=("$dep")
  fi
 done
 for dep in "${RADIAL_JARS[@]}"; do RADIAL_CP="$RADIAL_CP:$dep"; done
 echo "RadialGamePad: ${#RADIAL_JARS[@]} arquivos Java/Kotlin incluidos no DEX"
fi
javac -source 8 -target 8 -encoding UTF-8 -cp "$RADIAL_CP" \
 -d "$STAGE/classes" android/src/com/retroaura/lasrecomp/*.java "${SDLJAVA[@]}"
# Compile the actual original RadialGamePad integration Kotlin module only
# when explicitly enabled. Do not silently generate a legacy-looking APK.
if [[ -n "$RADIAL_AAR" ]]; then
 command -v kotlinc >/dev/null 2>&1 || fail "kotlinc nao instalado no Termux (necessario para NeoRadialControls.kt)"
 KOTLIN_SRC="android/kotlin/com/retroaura/lasrecomp/NeoRadialControls.kt"
 [[ -s "$KOTLIN_SRC" ]] || fail "Modulo Kotlin NeoRadialControls.kt ausente"
 # Java classes are compiled first; Kotlin sees both the app's bridge and
 # original RadialGamePad classes, including the explicit dependency jars.
 kotlinc "$KOTLIN_SRC" -jvm-target 1.8 -classpath "$RADIAL_CP:$STAGE/classes" -d "$STAGE/classes" ||
  fail "Falha ao compilar os controles originais Kotlin"
 [[ -s "$STAGE/classes/com/retroaura/lasrecomp/NeoRadialControls.class" ]] ||
  fail "NeoRadialControls.class nao foi gerado"
 echo "Controle original NeoRadialControls compilado."
fi
jar cf "$STAGE/classes.jar" -C "$STAGE/classes" .
# Avoid stale classes2.dex from an earlier optional dependency build.
rm -f "$STAGE/dex"/classes*.dex
"${D8_CMD[@]}" --min-api 26 --lib "$ANDROID_JAR" --output "$STAGE/dex" "$STAGE/classes.jar" "${RADIAL_JARS[@]}"
[[ -s "$STAGE/dex/classes.dex" ]] || fail "D8 nao gerou classes.dex"
# libc++ ARM64 do NDK, necessaria para simbolos C++ do runtime.
TERMUX_CXX="$PREFIX/lib/libc++_shared.so"
[[ -s "$TERMUX_CXX" ]] || fail "libc++_shared.so do Termux ausente: $TERMUX_CXX"
llvm-nm -D "$TERMUX_CXX" | grep '_ZNSt6__ndk113__hash_memoryEPKvm' >/dev/null || fail "libc++ do Termux nao exporta __hash_memory"
cp -L "$TERMUX_CXX" "$STAGE/lib/arm64-v8a/libc++_shared.so"
# O runtime deve referenciar explicitamente a libc++ empacotada,
# evitando resolver acidentalmente simbolos na libc++ do sistema.
patchelf --add-needed libc++_shared.so "$STAGE/lib/arm64-v8a/liblasrecomp_runtime.so"
LIBDIR="$STAGE/lib/arm64-v8a"
# Normaliza a dependencia zlib do Termux para o SONAME Android.
# Nao copia bibliotecas do ambiente Termux para o APK.
for so in "$LIBDIR"/*.so; do
 if llvm-readelf -d "$so" | grep -q 'Shared library: \[libz.so.1\]'; then
  patchelf --replace-needed libz.so.1 libz.so "$so"
 fi
done
for so in "$LIBDIR"/*.so; do
 patchelf --remove-rpath "$so"
 is_arm64_so "$so" || {
  echo "Cabeçalho ELF da biblioteca rejeitada:" >&2
  llvm-readelf -h "$so" 2>&1 | grep -E 'Class:|Machine:' || true
  fail "Biblioteca nao ARM64: $so"
 }
 soname="$(llvm-readelf -d "$so" | sed -n 's/.*(SONAME).*\[\([^]]*\)\].*/\1/p' | head -1)"
 [[ -z "$soname" || "$soname" == "$(basename "$so")" ]] || fail "SONAME errado: $so -> $soname"
 llvm-readelf -d "$so" | grep -Eq 'RUNPATH|RPATH' && fail "RPATH nao permitido: $so"
 while IFS= read -r dep; do
  [[ -z "$dep" || -s "$LIBDIR/$dep" ]] && continue
  case "$dep" in
   libc.so|libm.so|libdl.so|liblog.so|libandroid.so|libz.so|libvulkan.so|libEGL.so|libGLESv1_CM.so|libGLESv2.so|libGLESv3.so|libOpenSLES.so|libaaudio.so|libmediandk.so|libjnigraphics.so|libstdc++.so) continue;;
  esac
  fail "Dependencia Android ausente: $(basename "$so") -> $dep"
 done < <(llvm-readelf -d "$so" | sed -n 's/.*(NEEDED).*Shared library: \[\([^]]*\)\].*/\1/p')
done
APK="$OUT/LASRecomp-Android-Termux.apk"
rm -f -- "$OUT/unsigned.apk" "$OUT/aligned.apk" "$APK"
aapt2 link -I "$ANDROID_JAR" --manifest android/bootstrap/AndroidManifest.xml -o "$OUT/unsigned.apk"
(cd "$STAGE" && zip -q -r "$OUT/unsigned.apk" lib assets)
(cd "$STAGE/dex" && zip -q "$OUT/unsigned.apk" classes*.dex)
if [[ -n "$ZIPALIGN_CMD" ]]; then
 "$ZIPALIGN_CMD" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
else
 cp "$OUT/unsigned.apk" "$OUT/aligned.apk"
fi
KEYSTORE="${LASRECOMP_KEYSTORE:-$HOME/.lasrecomp-android-debug.keystore}"
if [[ ! -s "$KEYSTORE" ]]; then
 mkdir -p "$(dirname "$KEYSTORE")"
 keytool -genkeypair -noprompt -keystore "$KEYSTORE" \
  -storepass android -keypass android -alias androiddebugkey \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=LASRecomp Termux Debug,O=RetroAura,C=BR"
 chmod 600 "$KEYSTORE"
fi
${APKSIGNER_CMD} sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey \
 --ks-pass pass:android --key-pass pass:android --out "$APK" "$OUT/aligned.apk"
${APKSIGNER_CMD} verify "$APK"
if [[ -d "$HOME/storage/downloads" ]]; then
 mkdir -p "$HOME/storage/downloads/LASRecomp"
 cp -f "$APK" "$HOME/storage/downloads/LASRecomp/LASRecomp-Android-Termux.apk"
 echo "APK: $HOME/storage/downloads/LASRecomp/LASRecomp-Android-Termux.apk"
else
 echo "APK: $APK"
fi
echo "LOG: $OUT/compilacao.log"
[[ -n "${LASRECOMP_GAME_SO:-}" ]] || echo "AVISO: sem liblasgame.so privada, o APK nao inicia o jogo."
echo "Build/assinatura verificados. Boot do jogo requer teste real."
