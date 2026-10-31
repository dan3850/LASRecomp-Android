#!/data/data/com.termux/files/usr/bin/bash
# Build official ScarletNX Android APK, without rebuilding Zelda AOT.
set -euo pipefail
ROOT="$HOME/.cache/lasrecomp-scarletnx-upgrade"
SRC="$ROOT/ScarletNX"
OUT="$ROOT/scarletnx-android-apk-2026"
LLVM="$ROOT/android-llvm"
NDK="${ANDROID_NDK_ROOT:-}"
if [[ -z "$NDK" ]]; then
  SDK="${ANDROID_HOME:-$HOME/android-sdk}"
  NDK="$(find "$SDK/ndk" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V | tail -1)"
fi
[[ -f "$NDK/build/cmake/android.toolchain.cmake" ]] || { echo "ERRO: NDK Android nao encontrado"; exit 1; }
[[ -f "$SRC/scripts/android-apk.sh" ]] || { echo "ERRO: checkout ScarletNX ausente"; exit 1; }
[[ "$(git -C "$SRC" rev-parse HEAD)" == "05324b57629d0894506b31beb2c72869138b7ad1" ]] || { echo "ERRO: upstream nao corresponde a versao auditada"; exit 1; }
export ANDROID_NDK_ROOT="$NDK"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
if [[ -z "${GRADLE:-}" ]]; then
  if command -v gradle >/dev/null 2>&1; then GRADLE="$(command -v gradle)"
  else
    for candidate in "$HOME/gradle/bin/gradle" "$HOME/gradle-9.2.1/bin/gradle" "$HOME/gradle-9.1.0/bin/gradle" "$PREFIX/bin/gradle"; do
      if [[ -x "$candidate" ]]; then GRADLE="$candidate"; break; fi
    done
  fi
fi
if [[ -z "${GRADLE:-}" ]]; then
  echo "ERRO: Gradle nao encontrado. Procure: find \"\$HOME\" -maxdepth 5 -type f -path '*/bin/gradle' 2>/dev/null"
  echo "Defina GRADLE=/caminho/para/bin/gradle (Gradle 9)."
  exit 2
fi
export GRADLE
echo "Gradle localizado: $GRADLE"
for cmd in cmake ninja javac; do command -v "$cmd" >/dev/null || { echo "ERRO: ferramenta ausente: $cmd"; exit 1; }; done
if [[ ! -f "$LLVM/arm64-v8a/lib/cmake/llvm/LLVMConfig.cmake" ]]; then
  echo "=== LLVM ANDROID AINDA NAO COMPILADO ==="
  echo "O libLLVM.so do Termux nao substitui a toolchain LLVM NDK do APK."
  echo "Compile uma vez o LLVM Android oficial (pode consumir bastante tempo e espaco):"
  echo "  cd '$SRC'"
  echo "  ANDROID_NDK_ROOT='$NDK' ANDROID_HOME='$ANDROID_HOME' LLVM_VERSION=23.1.3 scripts/android-llvm.sh arm64-v8a '$LLVM/arm64-v8a'"
  exit 2
fi
# Restore original ScarletNX MainActivity launcher.
DIAG_SRC="$(cd "$(dirname "$0")" && pwd)/android/scarletnx-diagnostic/DiagnosticActivity.java"
DIAG_DST="$SRC/dist/android/src/main/java/org/scarletnx/DiagnosticActivity.java"
MANIFEST="$SRC/dist/android/src/main/AndroidManifest.xml"
[[ -f "$DIAG_SRC" && -f "$MANIFEST" ]] || { echo "ERRO: arquivos do diagnostico ausentes"; exit 1; }
cp "$DIAG_SRC" "$DIAG_DST"
python3 - "$MANIFEST" <<'PY'
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
p=Path(sys.argv[1])
ET.register_namespace("android","http://schemas.android.com/apk/res/android")
tree=ET.parse(p); root=tree.getroot()
ns="{http://schemas.android.com/apk/res/android}"
app=root.find("application")
if app is None: raise SystemExit("ERRO: application ausente")
main=next((a for a in app.findall("activity") if a.get(ns+"name")==".MainActivity"),None)
if main is None: raise SystemExit("ERRO: MainActivity ausente")
for a in app.findall("activity"):
    for filt in list(a.findall("intent-filter")):
        if any(c.get(ns+"name")=="android.intent.category.LAUNCHER" for c in filt.findall("category")):
            a.remove(filt)
filt=ET.SubElement(main,"intent-filter")
ET.SubElement(filt,"action",{ns+"name":"android.intent.action.MAIN"})
ET.SubElement(filt,"category",{ns+"name":"android.intent.category.LAUNCHER"})
diag=next((a for a in app.findall("activity") if a.get(ns+"name")==".DiagnosticActivity"),None)
if diag is None: ET.SubElement(app,"activity",{ns+"name":".DiagnosticActivity",ns+"exported":"false"})
else: diag.set(ns+"exported","false")
tree.write(p,encoding="unicode",xml_declaration=True)
print("ORIGINAL_SCARLETNX_LAUNCHER_OK")
PY
echo "=== COMPILANDO APK ANDROID SCARLETNX (SEM RECOMPILAR ZELDA) ==="
mkdir -p "$OUT"
export SCARLETNX_BUILD_JOBS="${SCARLETNX_BUILD_JOBS:-2}"
# The official script chooses the device CPU count; keep build bounded via CMAKE_BUILD_PARALLEL_LEVEL.
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
# LLVM Android was compiled with API 24; the runtime must use the same API.
export ANDROID_API=24
LIB="$NDK/toolchains/llvm/prebuilt/lib/clang/21/lib/aarch64-none-linux-android33"
SYSROOT="$NDK/toolchains/llvm/prebuilt/sysroot"
CXXLIB="$SYSROOT/usr/lib/aarch64-linux-android"
[[ -f "$LIB/libatomic.a" && -f "$LIB/libunwind.a" && -f "$CXXLIB/libc++_shared.so" ]] || {
  echo "ERRO: bibliotecas ARM64 do NDK incompletas"; exit 1;
}
# Reject a Termux-hosted clang masquerading as an NDK toolchain. A proper
# Android NDK link must use the NDK sysroot, crtbegin_so.o and libc.so.
# Termux clang may otherwise embed its own Bionic implementation in libmain.so.
NDK_CLANG="$NDK/toolchains/llvm/prebuilt/bin/clang++"
NDK_SYSROOT="$NDK/toolchains/llvm/prebuilt/sysroot"
DRIVER_TRACE="$("$NDK_CLANG" --target=aarch64-none-linux-android24 -shared -### -x c++ /dev/null -o /dev/null 2>&1)"
if ! grep -Fq "$NDK_SYSROOT" <<< "$DRIVER_TRACE" || \
   grep -Eq '/data/data/com\\.termux/files/usr/(lib|bin|tmp)' <<< "$DRIVER_TRACE"; then
  echo "ERRO: clang do NDK usa bibliotecas ou sysroot do Termux." >&2
  echo "Nao compilar libmain.so: toolchain Android contaminada." >&2
  echo "$DRIVER_TRACE" | grep -E 'ld\\.lld|crtbegin|crtend|sysroot| -lc' >&2 || true
  exit 2
fi
LINK_FLAGS="-L$LIB -L$CXXLIB"
# OpenSSL invokes the NDK compiler by its standard target-prefixed name.
# Termux-native NDK adaptations may omit these wrappers. Create them in a
# private PATH directory, never inside the NDK.
WRAPPER_DIR="$ROOT/ndk-bin"
mkdir -p "$WRAPPER_DIR"
for api in 21 24; do
  for compiler in clang clang++; do
    wrapper="$WRAPPER_DIR/aarch64-linux-android${api}-$compiler"
    printf '#!/data/data/com.termux/files/usr/bin/sh\nexec "%s" --target=aarch64-none-linux-android%s "$@"\n' \
      "$NDK/toolchains/llvm/prebuilt/bin/$compiler" "$api" > "$wrapper"
    chmod 755 "$wrapper"
  done
done
# ExternalProject's OpenSSL configure/build receives PATH through cmake -E env.
export PATH="$WRAPPER_DIR:$PATH"
echo "OpenSSL compiler: $(command -v aarch64-linux-android24-clang)"

# The previous APK crashed inside a getauxval implementation embedded in libmain.so.
# Never reuse native objects from that build: regenerate the Android native tree.
if [[ "${SCARLETNX_CLEAN_NATIVE:-1}" == "1" ]]; then
  echo "=== LIMPANDO BUILD NATIVA ANTERIOR (SEM APAGAR LLVM) ==="
  rm -rf "$OUT/arm64-v8a"
fi
# Remove only CMake configuration from previous failed API 21 attempt.
if [[ -f "$OUT/arm64-v8a/CMakeCache.txt" ]] && grep -q 'ANDROID_PLATFORM:.*android-21' "$OUT/arm64-v8a/CMakeCache.txt"; then
  rm -f "$OUT/arm64-v8a/CMakeCache.txt"
fi
echo "Android API: $ANDROID_API"
echo "Bibliotecas NDK: $LINK_FLAGS"
bash "$SRC/scripts/android-apk.sh" "$OUT" "$LLVM" arm64-v8a -- \
  "-DCMAKE_EXE_LINKER_FLAGS=$LINK_FLAGS" \
  "-DCMAKE_SHARED_LINKER_FLAGS=$LINK_FLAGS" \
  "-DCMAKE_MODULE_LINKER_FLAGS=$LINK_FLAGS"
# The Android Gradle project packages native libraries from stage/lib.
# NDK libc++ is dynamically required by libmain.so; stage it explicitly.
# The official upstream script has already assembled the APK at this point,
# so rebuild only Gradle packaging when the C++ runtime was absent.
CXX_DST="$OUT/stage/lib/arm64-v8a/libc++_shared.so"
if [[ ! -s "$CXX_DST" ]]; then
  install -m 644 "$CXXLIB/libc++_shared.so" "$CXX_DST"
  echo "=== REEMPACOTANDO APK COM libc++_shared.so ==="
  "$GRADLE" -p "$SRC/dist/android" --project-cache-dir "$OUT/gradle-cache" assembleDebug \
    "-Pscarletnx.stage=$OUT/stage"
fi
APK="$OUT/stage/gradle/outputs/apk/debug/ScarletNX-debug.apk"
[[ -s "$APK" ]] || { echo "ERRO: APK nao foi gerado"; exit 1; }
if ! unzip -Z1 "$APK" | grep -qx 'lib/arm64-v8a/libc++_shared.so'; then
  echo "ERRO: APK nao contem libc++_shared.so"; exit 1
fi
# Reject broken Bionic linkage before shipping the APK.
READELF="$NDK/toolchains/llvm/prebuilt/bin/llvm-readelf"
NATIVE="$OUT/stage/lib/arm64-v8a/libmain.so"
[[ -s "$NATIVE" && -x "$READELF" ]] || { echo "ERRO: nao foi possivel validar libmain.so"; exit 2; }
if ! "$READELF" -d "$NATIVE" | grep -Eq 'NEEDED.*libc[.]so'; then
  echo "ERRO: libmain.so sem dependencia dinamica de libc.so; build nativa incorreta."
  exit 2
fi
# getauxval must come from Android's Bionic, not be defined by libmain.so.
# A locally defined implementation was the crash site in the supplied tombstone.
NM="$NDK/toolchains/llvm/prebuilt/bin/llvm-nm"
[[ -x "$NM" ]] || { echo "ERRO: llvm-nm ausente"; exit 2; }
if "$NM" -D --defined-only "$NATIVE" | grep -Eq '[[:space:]][TW][[:space:]]+getauxval(@@?.*)?
echo "APK_CXX_RUNTIME_OK=$APK"
echo "=== APKS GERADOS ==="
find "$OUT/stage/gradle/outputs/apk" -type f -name '*.apk' -print
echo "NOTA: o APK e o app original. O Zelda AOT permanece no staging privado e deve ser importado para games/ pelo app."
; then
  echo "ERRO CRITICO: libmain.so define getauxval localmente; risco de crash SIGSEGV."
  echo "Corrija a origem da biblioteca Bionic antes de instalar."
  exit 2
fi
echo "ANDROID_GETAUXVAL_EXTERNAL_OK"
echo "ANDROID_BIONIC_LIBC_LINK_OK"
echo "APK_CXX_RUNTIME_OK=$APK"
echo "=== APKS GERADOS ==="
find "$OUT/stage/gradle/outputs/apk" -type f -name '*.apk' -print
echo "NOTA: o APK e o app original. O Zelda AOT permanece no staging privado e deve ser importado para games/ pelo app."
