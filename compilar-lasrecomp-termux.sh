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
for cmd in git clang clang++ cmake ninja make llvm-ar llvm-nm llvm-readelf llvm-ranlib llvm-strip python3 javac jar keytool aapt2 d8 zip zipalign apksigner patchelf; do
  command -v "$cmd" >/dev/null 2>&1 || fail "Falta $cmd. pkg install git clang cmake ninja make python openjdk-21 android-sdk aapt2 d8 zip zipalign apksigner patchelf"
done
python3 -c 'import fontTools' 2>/dev/null || fail "Instale pkg install python-fonttools"
ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$PREFIX/opt/android-sdk}}"
[[ -d "$ANDROID_HOME/platforms" ]] || ANDROID_HOME="$HOME/android-sdk"
ANDROID_JAR="${ANDROID_JAR:-$(find "$ANDROID_HOME/platforms" -name android.jar -type f 2>/dev/null | sort -V | tail -1)}"
[[ -s "$ANDROID_JAR" ]] || fail "SDK android.jar ausente. Configure ANDROID_HOME."
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
 -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384" -DANDROID=ON)
step "SDL3 — compila do fonte"
cmake -S "$DEPS/sdl3" -B "$WORK/sdl3" "${CMAKE_OPTS[@]}" \
 -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TEST_LIBRARY=OFF \
 -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF -DSDL_ANDROID=ON
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
step "FFmpeg estatico ARM64"
FFDEST="$WORK/ffmpeg-install"
mkdir -p "$FFDEST"
if [[ ! -s "$DEPS/ffmpeg/ffbuild/config.mak" ]]; then
 (cd "$DEPS/ffmpeg" && ./configure --prefix="$FFDEST" --target-os=android \
   --arch=aarch64 --cpu=armv8-a --cc=clang --cxx=clang++ \
   --ar=llvm-ar --nm=llvm-nm --ranlib=llvm-ranlib --strip=llvm-strip \
   --enable-pic --disable-doc --disable-programs --enable-static \
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
 mkdir -p "$(dirname "$obj")"
 if [[ ! -s "$obj" || "$src" -nt "$obj" || "$STAMP" -nt "$obj" ]]; then
  echo "CC ${src#"$ROOT"/}"
  "$compiler" -O2 -fPIC -fno-strict-aliasing \
   -Wno-nullability-completeness "$@" -c "$src" -o "$obj.tmp"
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
step "Compilando Vulkan/ImGui"
mkdir -p "$OBJ/inc"
LC_ALL=C tr -d '\r' < third_party/smaa/SMAA.hlsl \
 | LC_ALL=C tr '\200-\377' '?' \
 | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/^/"/' -e 's/$/\\n"/' \
 > "$OBJ/inc/smaa_hlsl.inc"
INC=(-Iruntime -Iruntime/nvn -Ithird_party/imgui \
 -Ithird_party/imgui/backends -Ithird_party/smaa/Textures \
 -I"$SDL_HEADERS" -I"$DEPS/shaderc/libshaderc/include" \
 -I"$DEPS/vma/include" -I"$DEPS/volk" -I"$OBJ/inc")
RENDER=()
while IFS= read -r src; do
 obj="$OBJ/renderer/${src#"$ROOT"/}.o"
 cc=clang; std=-std=gnu11
 [[ "$src" == *.cpp ]] && { cc=clang++; std=-std=c++17; }
 compile "$src" "$obj" "$cc" "$std" -DVK_NO_PROTOTYPES \
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
  -Iruntime -Iruntime/nvn -Iruntime/ui -Ithird_party/imgui \
  -Ithird_party/imgui/backends -I"$SDL_HEADERS" \
  -I"$FFDEST/include" -I"$DEPS/vma/include" -I"$DEPS/volk"
 UI+=("$obj")
done
RUNTIME="$LIB/liblasrecomp_runtime.so"
clang++ -shared -Wl,-z,max-page-size=16384 -Wl,--no-undefined \
 -Wl,-soname,liblasrecomp_runtime.so -o "$RUNTIME.tmp" "${UI[@]}" \
 -Wl,--whole-archive "$LIB/liblasrecomp-core.a" \
 "$LIB/liblasrecomp-renderer.a" -Wl,--no-whole-archive \
 -L"$(dirname "$SDL_SO")" -L"$(dirname "$SHADERC_SO")" \
 -lSDL3 -lshaderc_shared -Wl,--start-group \
 "$FFDEST/lib/libavformat.a" "$FFDEST/lib/libavcodec.a" \
 "$FFDEST/lib/libavutil.a" "$FFDEST/lib/libswscale.a" \
 "$FFDEST/lib/libswresample.a" -Wl,--end-group -llog -landroid -ldl -lz -lm
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
step "Empacotando APK novo (sem modificar motor)"
STAGE="$OUT/stage"
mkdir -p "$STAGE/lib/arm64-v8a" "$STAGE/assets" "$STAGE/dex" "$STAGE/classes"
for so in "$SDL_SO" "$SHADERC_SO" "$RUNTIME" "$LIB/libmain.so" \
 "$LIB/liblasrecomp_prepare.so" "$LIB/liblasrecomp_probe.so"; do
 cp -L "$so" "$STAGE/lib/arm64-v8a/$(basename "$so")"
done
if [[ -n "${LASRECOMP_GAME_SO:-}" ]]; then
 [[ -s "$LASRECOMP_GAME_SO" ]] || fail "LASRECOMP_GAME_SO ausente"
 llvm-nm -D --defined-only "$LASRECOMP_GAME_SO" \
  | grep -Eq '[[:space:]]lasgame_tables$' || fail "lasgame_tables ausente"
 cp -L "$LASRECOMP_GAME_SO" "$STAGE/lib/arm64-v8a/liblasgame.so"
fi
NDK="${ANDROID_NDK_HOME:-}"
if [[ -z "$NDK" ]]; then
 NDK="$(find "$ANDROID_HOME/ndk" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V | tail -1)"
fi
[[ -d "$NDK" ]] || fail "NDK do Android nao encontrado (necessario apenas libc++_shared.so; nao executa binarios x86)."
CXX_SHARED="$(find "$NDK/toolchains/llvm/prebuilt" -type f -path '*/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so' -print -quit)"
[[ -s "$CXX_SHARED" ]] || fail "libc++_shared.so ausente no NDK"
cp "$CXX_SHARED" "$STAGE/lib/arm64-v8a/libc++_shared.so"
python3 tools/android-font-fallback.py \
 third_party/imgui/misc/fonts/Roboto-Medium.ttf "$STAGE/assets/lasrecomp_font.ttf"
mapfile -d '' -t SDLJAVA < <(find "$SDL_JAVA" -type f -name '*.java' -print0)
(( ${#SDLJAVA[@]} > 0 )) || fail "SDL Java nao encontrado"
javac -source 8 -target 8 -encoding UTF-8 -cp "$ANDROID_JAR" \
 -d "$STAGE/classes" android/src/com/retroaura/lasrecomp/*.java "${SDLJAVA[@]}"
jar cf "$STAGE/classes.jar" -C "$STAGE/classes" .
d8 --min-api 26 --lib "$ANDROID_JAR" --output "$STAGE/dex" "$STAGE/classes.jar"
[[ -s "$STAGE/dex/classes.dex" ]] || fail "D8 nao gerou classes.dex"
LIBDIR="$STAGE/lib/arm64-v8a"
for so in "$LIBDIR"/*.so; do
 patchelf --remove-rpath "$so"
 llvm-readelf -h "$so" | grep -q AArch64 || fail "Biblioteca nao ARM64: $so"
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
aapt2 link -I "$ANDROID_JAR" --manifest android/bootstrap/AndroidManifest.xml -o "$OUT/unsigned.apk"
(cd "$STAGE" && zip -q -r "$OUT/unsigned.apk" lib assets)
(cd "$STAGE/dex" && zip -q "$OUT/unsigned.apk" classes.dex)
zipalign -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
KEYSTORE="${LASRECOMP_KEYSTORE:-$HOME/.lasrecomp-android-debug.keystore}"
if [[ ! -s "$KEYSTORE" ]]; then
 mkdir -p "$(dirname "$KEYSTORE")"
 keytool -genkeypair -noprompt -keystore "$KEYSTORE" \
  -storepass android -keypass android -alias androiddebugkey \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=LASRecomp Termux Debug,O=RetroAura,C=BR"
 chmod 600 "$KEYSTORE"
fi
apksigner sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey \
 --ks-pass pass:android --key-pass pass:android --out "$APK" "$OUT/aligned.apk"
apksigner verify "$APK"
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
