#!/data/data/com.termux/files/usr/bin/bash
# Separate, genuine ScarletNX CPU/Horizon/Vulkan runtime with a user-built ABI12 AOT .so.
# Never commits Nintendo-derived binaries or changes the existing LASRecomp boot build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
die() { echo "ERRO: $*" >&2; exit 1; }
[ "$(uname -m)" = aarch64 ] || die "Termux ARM64 necessario"
[ "$(git branch --show-current)" = experimental/castlevania-belmonts-curse ] ||
[ "$(git branch --show-current)" = experimental/ryujinx-runtime-nativeaot ] ||
[ "$(git branch --show-current)" = experimental/zelda-links-awakening-ryujinx-nativeaot ] ||
  die "Selecione branch experimental do Castlevania/Ryujinx NativeAOT"
for tool in unzip zip llvm-readelf llvm-nm patchelf; do
  command -v "$tool" >/dev/null || die "Falta ferramenta $tool"
done

SNX_CODE="${ZELDA_SNX_CODE_SO:-}"
[ -n "$SNX_CODE" ] || SNX_CODE="/storage/emulated/0/Download/01006BB00C6F0000 (1)/01006BB00C6F0000_code.so"
[ -s "$SNX_CODE" ] || die "Modulo recompilado ausente: $SNX_CODE"
llvm-nm -D --defined-only "$SNX_CODE" | grep -E '[[:space:]]snx_module$' >/dev/null ||
  die "Modulo sem snx_module"
ABI_FILE="$(dirname "$SNX_CODE")/01006BB00C6F0000.abi"
[ ! -s "$ABI_FILE" ] || [ "$(cat "$ABI_FILE")" = 12 ] ||
  die "Requer ABI 12"

CACHE="$HOME/.cache/lasrecomp-mario-snx"
mkdir -p "$CACHE"
SNX_APK="$(printenv SCARLETNX_APK || true)"
if [ -z "$SNX_APK" ]; then
  INSTALLED="$(pm path org.scarletnx 2>/dev/null | sed -n 's/^package://p' | head -1 || true)"
  if [ -n "$INSTALLED" ] && [ -r "$INSTALLED" ]; then
    SNX_APK="$INSTALLED"
    echo "Usando ScarletNX original instalado no celular."
  fi
fi
if [ -z "$SNX_APK" ]; then
  for candidate in \
    /storage/emulated/0/Download/ScarletNX-android-universal.apk \
    /storage/emulated/0/Download/ScarletNX.apk; do
    if [ -s "$candidate" ]; then SNX_APK="$candidate"; break; fi
  done
fi
if [ -z "$SNX_APK" ]; then
  SNX_APK="$CACHE/ScarletNX-android-universal.apk"
  if [ ! -s "$SNX_APK" ]; then
    echo "Baixando ScarletNX original (apenas uma vez)..."
    curl -fL --retry 2 -o "$SNX_APK.partial" \
      https://github.com/scarletnx/nightly/releases/latest/download/ScarletNX-android-universal.apk ||
      die "Download falhou; defina SCARLETNX_APK=/caminho/apk-original"
    mv "$SNX_APK.partial" "$SNX_APK"
  fi
fi
[ -r "$SNX_APK" ] || die "ScarletNX APK ilegivel: $SNX_APK"
unzip -Z1 "$SNX_APK" | grep -Fx 'lib/arm64-v8a/libscarletnx.so' >/dev/null ||
  die "APK ScarletNX sem runtime arm64"

# The Castlevania AOT is already emitted by ScarletNX (snx_module ABI 12).
# LASRecomp's old private Mario library and boot profile are a separate engine
# and MUST NOT be prerequisites or accidentally packaged into this test APK.
OUT="$ROOT/build/zelda-snx-runtime-boot"
unset LASRECOMP_MARIO_PROFILE LASRECOMP_GAME_SO
export LASRECOMP_BUILD_OUT="$OUT"
export LASRECOMP_MANIFEST="$ROOT/android/castlevania/AndroidManifest.xml"
export LASRECOMP_APK_FILENAME=Zelda-SNX-Runtime-TESTE.apk
export LASRECOMP_DOWNLOAD_FOLDER=ZeldaRecomp
# This APK launches ScarletNX directly; the LASRecomp-only RadialGamePad
# frontend would bring extra dependencies without controlling ScarletNX.
export LASRECOMP_NEO_CONTROLS=0
python3 tests/test_mario_snx_probe.py
echo "===== PREPARANDO BIBLIOTECAS SCARLETNX ANTES DO APK ====="
EXTRA="$OUT/snx-stage"
rm -rf "$EXTRA"
mkdir -p "$EXTRA/lib/arm64-v8a" "$EXTRA/assets/licenses"
if [ "${SCARLETNX_ZELDA_PERF:-0}" = 1 ]; then
  git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-PERF.txt"
  if [ "${SCARLETNX_ZELDA_NXNATIVE:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-NXNative.txt"
  fi
  if [ "${SCARLETNX_ZELDA_UNIFORM:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-Uniforms.txt"
  fi
  if [ "${SCARLETNX_ZELDA_CLEAR_LOAD:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-Clears.txt"
  fi
  if [ "${SCARLETNX_ZELDA_UB_EXTENT:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-UniformExtent.txt"
  fi
  if [ "${SCARLETNX_ZELDA_BIND_REUSE:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-Bindings.txt"
  fi
  if [ "${SCARLETNX_ZELDA_VB_POOL:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-PersistentBuffers.txt"
  fi
  if [ "${SCARLETNX_ZELDA_DEPTH_RANGE:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-DepthRange.txt"
  fi
  if [ "${SCARLETNX_ZELDA_LIGHT_DIAG:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-LightDiagnostics.txt"
  fi
  if [ "${SCARLETNX_ZELDA_EFFECT_DEPTH:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-EffectDepth.txt"
  fi
  if [ "${SCARLETNX_ZELDA_D24_COPIES:-0}" = 1 ]; then
    git rev-parse HEAD > "$EXTRA/assets/licenses/Zelda-D24Copies.txt"
  fi
fi
SNLIB="$EXTRA/lib/arm64-v8a"
# Cross-check against the previous LASRecomp test's native library names.
# That stage is NOT modified; the freshly compiled stage is made afterwards.
# The general Android builder will produce its own libraries; no Mario stage.
# Use staged copies only if this experimental APK was already built.
MAINLIB="$OUT/stage/lib/arm64-v8a"
# The original APK runtime cannot graft an external RomFS directory.
# Explicitly require a rebuilt ScarletNX with tools/patch_scarletnx_romfs.py;
# fail instead of delivering another APK with the known FS_TREE_INVALID error.
SNX_PATCHED_RUNTIME="${SCARLETNX_PATCHED_RUNTIME_SO:-$HOME/scarletnx-romfs-build/libscarletnx.so}"
[ -s "$SNX_PATCHED_RUNTIME" ] ||
  die "Runtime ScarletNX com suporte RomFS ainda nao compilado: $SNX_PATCHED_RUNTIME. Veja tools/patch_scarletnx_romfs.py."
python3 "$ROOT/tools/scarletnx_elf_audit.py" "$SNX_PATCHED_RUNTIME" \
  --require-main --require-trace --output "$CACHE/runtime-input-elf.json"
[ -s "$SNX_PATCHED_RUNTIME.link.json" ] ||
  die "Proveniencia libc/C++ ausente. Execute compilar-mario-snx-romfs-termux.sh."
SNX_CXX="$(python3 - "$SNX_PATCHED_RUNTIME" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
runtime = Path(sys.argv[1])
metadata = json.loads(Path(str(runtime) + '.link.json').read_text())
for path, expected in [(runtime, metadata['runtime_sha256']),
                       (Path(metadata['cxx']), metadata['cxx_sha256'])]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Runtime/C++ mudou desde o link; reexecute o build incremental: ' + str(path))
print(metadata['cxx'])
PY
)"
cp -L "$SNX_PATCHED_RUNTIME" "$SNLIB/libscarletnx.so"
grep -aF 'SNX_EXTERNAL_ROMFS' "$SNLIB/libscarletnx.so" >/dev/null ||
  die "Runtime sem patch SNX_EXTERNAL_ROMFS; compilacao interrompida para evitar FS_TREE_INVALID"
echo "SCARLETNX: runtime com graft externo confirmado"
# Do not use grep -q here: with "set -o pipefail" and a big symbol
# table, an early grep match may SIGPIPE llvm-nm and incorrectly fail the build.
# Save the whole table once and check it AFTER llvm-nm has exited normally.
RUNTIME_SYMBOLS="$CACHE/scarletnx-runtime-exports.txt"
if ! llvm-nm -D --defined-only "$SNLIB/libscarletnx.so" > "$RUNTIME_SYMBOLS"; then
  die "Nao foi possivel ler os simbolos do runtime ScarletNX"
fi
# The entire nm table is already saved. Reading it from disk avoids SIGPIPE
# false negatives caused by grep -q while the producer is still writing.
if ! grep -E '[[:space:]]main(@[^[:space:]]*)?$' "$RUNTIME_SYMBOLS" >/dev/null; then
  echo '===== ENTRADAS EXPORTADAS PELO RUNTIME ====='
  grep -Ei '(main|scarlet|snx|SDL_)' "$RUNTIME_SYMBOLS" | tail -45 || true
  echo "ScarletNX APK utilizado: $SNX_APK"
  die 'O runtime ScarletNX nao exporta main. Nao vamos iniciar com ABI errada.'
fi
echo 'SCARLETNX RUNTIME ENTRY VERIFIED:'
grep -E '[[:space:]]main(@[^[:space:]]*)?$' "$RUNTIME_SYMBOLS" | head -1

# Import original native dependencies and namespace any ELF SONAME collision
# with LASRecomp's own JNI/runtime libraries. Different game processes isolate SDL.
MAP="$CACHE/library-name-map.txt"
printf '%s\n' 'libc++_shared.so libsnx_c++_shared.so' > "$MAP"
COPIED="$CACHE/packaged-scarlet-libraries.txt"
printf '%s\n' "$SNLIB/libscarletnx.so" > "$COPIED"
# Use precisely the C++ file used by this build and shared LLVM. Renaming the
# original APK's older C++ and importing a second one for LLVM splits the ABI.
cp -L "$SNX_CXX" "$SNLIB/libsnx_c++_shared.so"
patchelf --set-soname libsnx_c++_shared.so "$SNLIB/libsnx_c++_shared.so"
printf '%s\n' "$SNLIB/libsnx_c++_shared.so" >> "$COPIED"
while IFS= read -r member; do
  name="$(basename "$member")"
  case "$name" in
    libscarletnx.so|libmain.so|libscarletnx-run.so|libc++_shared.so) continue;;
  esac
  temp="$CACHE/original-$name"
  unzip -p "$SNX_APK" "$member" > "$temp"
  [ -s "$temp" ] || die "Nao extraiu $name"
  dest="$name"
  # Separate process, but the Android linker namespace is still shared by
  # nativeLibraryDir. Rename original ScarletNX dependencies to prevent
  # collisions with the app's SDL, libc++ and runtime .so files.
  dest="libsnx_$(printf %s "$name" | cut -c4-)"
  printf '%s %s\n' "$name" "$dest" >> "$MAP"
  cp "$temp" "$SNLIB/$dest"
  printf '%s\n' "$SNLIB/$dest" >> "$COPIED"
  if [ "$dest" != "$name" ]; then
    patchelf --set-soname "$dest" "$SNLIB/$dest"
  fi
done < <(unzip -Z1 "$SNX_APK" | grep -E '^lib/arm64-v8a/lib[^/]+\.so$' | sort -u)

while IFS= read -r elf; do
  while read -r original replacement; do
    [ -n "$original" ] || continue
    if llvm-readelf -d "$elf" | grep -F "Shared library: [$original]" >/dev/null; then
      patchelf --replace-needed "$original" "$replacement" "$elf"
    fi
  done < "$MAP"
done < "$COPIED"

cp -L "$SNX_CODE" "$SNLIB/libzelda_snx.so"
# The LIVE shader translator is an actual Android ELF produced by GitHub Actions.
# Only opt-in on the experimental NativeAOT branch; no precompiled shader packs.
# Put it into the normal APK nativeLibraryDir so Android's linker can dlopen it.
if [ "${SCARLETNX_RYU_NATIVE_PROBE_BUILD:-0}" = 1 ]; then
  { [ "$(git branch --show-current)" = experimental/ryujinx-runtime-nativeaot ] ||
    [ "$(git branch --show-current)" = experimental/zelda-links-awakening-ryujinx-nativeaot ]; } ||
    die "Biblioteca Ryujinx: somente branches NativeAOT experimentais"
  LIB_RYU="${SCARLETNX_RYU_NATIVE_SO:-$HOME/ryujinx-nativeaot/libRyujinxShaderNative.so}"
  [ -s "$LIB_RYU" ] || die "Biblioteca Ryujinx NativeAOT nao encontrada: $LIB_RYU"
  python3 "$ROOT/tools/ryujinx-nativeaot/check_native_elf.py" "$LIB_RYU"
  cp -L "$LIB_RYU" "$SNLIB/libRyujinxShaderNative.so"
  printf '%s\n' "$SNLIB/libRyujinxShaderNative.so" >> "$COPIED"
  echo "Ryujinx NativeAOT incluido no APK: $(du -h "$SNLIB/libRyujinxShaderNative.so")"
fi
cp android/licenses/RadialGamePad-GPL-3.0.txt "$EXTRA/assets/licenses/ScarletNX-GPL-3.0.txt"
if [ "${SCARLETNX_ZELDA_DEJAVU_FONT:-0}" = 1 ]; then
  cp "$ROOT/android/licenses/DejaVu-LICENSE.txt" "$EXTRA/assets/licenses/DejaVu-Bitstream-Vera.txt"
  echo "ZELDA_DEJAVU_LICENSE_STAGED: OK"
fi
cat > "$EXTRA/assets/licenses/ScarletNX-SOURCE.txt" <<'NOTICE'
ScarletNX experimental runtime (GPL-3.0-or-later):
https://github.com/scarletnx/ScarletNX
Copyright 2026 the ScarletNX contributors.
A test APK built locally from user-provided binaries; do not redistribute
Nintendo game dumps, extracted data, or Nintendo-derived generated code.
Distributing GPL-covered binaries requires corresponding source and compliance.
NOTICE

# Termux LLVM is built as a shared ARM64 library. Unlike the
# upstream APK's statically linked LLVM, this newly rebuilt ScarletNX
# needs libLLVM.so at runtime. Include it and any non-platform shared
# dependencies from the Termux prefix before validating the APK closure.
# Never overwrite already staged SDL/ScarletNX libraries or platform libs.
echo "===== COMPLETANDO DEPENDENCIAS LLVM ARM64 ====="
SYSTEM_LIBS=' libc.so libm.so libdl.so liblog.so libandroid.so libz.so libvulkan.so libEGL.so libGLESv1_CM.so libGLESv2.so libGLESv3.so libOpenSLES.so libaaudio.so libmediandk.so libjnigraphics.so libstdc++.so '
for dep in $(llvm-readelf -d "$SNLIB/libscarletnx.so" | sed -n 's/.*(NEEDED).*Shared library: \[\([^]]*\)\].*/\1/p'); do
  case "$dep" in
    libLLVM.so|libLLVM-*.so)
      candidate="$PREFIX/lib/$dep"
      [ -s "$candidate" ] || die "LLVM compartilhado requerido mas ausente: $candidate (confira ls -l $PREFIX/lib/libLLVM*)"
      cp -L "$candidate" "$SNLIB/$dep"
      printf '%s\n' "$SNLIB/$dep" >> "$COPIED"
      echo "LLVM empacotado: $dep"
      ;;
  esac
done
# Resolve all ELF dependencies recursively, including versioned Termux SONAMEs.
# Android APK native libraries need a .so filename. Rename versioned
# libraries privately and rewrite their NEEDED references accordingly.
# Keep the original files in $PREFIX untouched.
index=1
while :; do
  count="$(wc -l < "$COPIED")"
  [ "$index" -le "$count" ] || break
  [ "$index" -le 128 ] || die "Mais de 128 bibliotecas na cadeia de dependencias; interrompendo"
  elf="$(sed -n "${index}p" "$COPIED")"
  while IFS= read -r dep; do
    [ -n "$dep" ] || continue
    if [ "$dep" = libc++_shared.so ]; then
      patchelf --replace-needed libc++_shared.so libsnx_c++_shared.so "$elf"
      continue
    fi
    if [ "$dep" = libz.so.1 ]; then
      patchelf --replace-needed libz.so.1 libz.so "$elf"
      echo "SNX Android zlib: $(basename "$elf") libz.so.1 -> libz.so"
      continue
    fi
    [ -s "$SNLIB/$dep" ] && continue
    # MAINLIB belongs to a previous build and is not injected into this APK.
    # Never treat its files as satisfying the current SNX dependency closure.
    case "$SYSTEM_LIBS" in *" $dep "*) continue;; esac
    candidate="$PREFIX/lib/$dep"
    if [ ! -s "$candidate" ] && [ "$dep" = libffi.so ]; then
      # Some Termux libffi packages expose only a versioned ELF (libffi.so.8).
      # Keep the original installation untouched; copy it into the APK with
      # the exact unversioned DT_NEEDED name required by libLLVM.so.
      for alt in "$PREFIX"/lib/libffi.so.[0-9]*; do
        if [ -s "$alt" ] && llvm-readelf -h "$alt" | grep -F 'AArch64' >/dev/null; then
          candidate="$alt"
          echo "libffi.so nao versionada ausente; usando $(basename "$alt") apenas no APK"
          break
        fi
      done
    fi
    if [ ! -s "$candidate" ]; then
      echo "ERRO: biblioteca necessaria ao APK ausente: $(basename "$elf") -> $dep" >&2
      echo "Origem procurada: $PREFIX/lib/$dep" >&2
      echo "No Termux: pkg install libffi; ls -l $PREFIX/lib/libffi.so*" >&2
      die "Nao e seguro gerar APK com dependencia ELF faltando"
    fi
    dest="$dep"
    case "$dep" in
      *.so.[0-9]*)
        # e.g. libzstd.so.1 => libsnx_termux_zstd.so
        stem="${dep#lib}"
        stem="${stem%%.so.*}"
        dest="libsnx_termux_${stem}.so"
        [ -s "$SNLIB/$dest" ] || {
          cp -L "$candidate" "$SNLIB/$dest"
          patchelf --set-soname "$dest" "$SNLIB/$dest"
          printf '%s\n' "$SNLIB/$dest" >> "$COPIED"
          echo "Dependencia versionada: $dep -> $dest"
        }
        patchelf --replace-needed "$dep" "$dest" "$elf"
        ;;
      *)
        cp -L "$candidate" "$SNLIB/$dest"
        if [ "$dep" = libffi.so ] && [ "$(basename "$candidate")" != "$dep" ]; then
          patchelf --set-soname "$dep" "$SNLIB/$dest"
        fi
        printf '%s\n' "$SNLIB/$dest" >> "$COPIED"
        echo "Dependencia Termux empacotada: $dep"
        ;;
    esac
  done < <(llvm-readelf -d "$elf" | sed -n 's/.*(NEEDED).*Shared library: \[\([^]]*\)\].*/\1/p')
  index=$((index + 1))
done

# Native dependencies must be present in the final APK or Android system.
while IFS= read -r elf; do
  while IFS= read -r dep; do
    [ -n "$dep" ] || continue
    [ ! -s "$SNLIB/$dep" ] || continue
    # Validate against current SNX staging, not a stale previous build.
    case "$dep" in
      libc.so|libm.so|libdl.so|liblog.so|libandroid.so|libz.so|libvulkan.so|libEGL.so|libGLESv1_CM.so|libGLESv2.so|libGLESv3.so|libOpenSLES.so|libaaudio.so|libmediandk.so|libjnigraphics.so|libstdc++.so) continue;;
    esac
    die "Dependencia ScarletNX ausente: $dep"
  done < <(llvm-readelf -d "$elf" | sed -n 's/.*(NEEDED).*Shared library: \[\([^]]*\)\].*/\1/p')
done < "$COPIED"

# patchelf must not reintroduce private libc or change the selected C++ closure.
python3 "$ROOT/tools/scarletnx_elf_audit.py" "$SNLIB/libscarletnx.so" \
  --require-main --require-trace --cxx-dir "$SNLIB" \
  --output "$CACHE/runtime-staged-elf.json"

# Add all native libraries to the normal Android app's JNI staging BEFORE
# the APK is assembled and signed, not to an already-built ZIP. Android's
# package manager will see these as normal nativeLibraryDir entries.
export LASRECOMP_SNX_MODULE_NAME="libzelda_snx.so"
export LASRECOMP_SNX_STAGE_LIB_DIR="$SNLIB"
export LASRECOMP_SNX_STAGE_LICENSE_DIR="$EXTRA/assets/licenses"

# Android crash identified: ScarletNX's SDL 3.4.18 JNI_OnLoad requires
# SDLActivity.nativeSetupJNI()V. The LASRecomp-pinned SDL 3.2.22 Java declares
# nativeSetupJNI()I and aborts ART during System.loadLibrary(scarletnx).
# Fetch ONLY the pinned upstream SDL Java sources into a separate cache.
# Do not switch or clean the LASRecomp SDL 3.2.22 checkout/native build.
SDL_SOURCES="${LASRECOMP_CACHE:-$HOME/.cache/lasrecomp-termux}/src/sdl3"
SDL_VERSION=release-3.4.18
SDL_JAVA_CACHE="$CACHE/sdl-$SDL_VERSION"
SDL_JAVA="$SDL_JAVA_CACHE/android-project/app/src/main/java"
if [ ! -s "$SDL_JAVA/org/libsdl/app/SDLActivity.java" ]; then
  [ -d "$SDL_SOURCES/.git" ] || die "Checkout do SDL do LASRecomp ausente: $SDL_SOURCES"
  echo "===== OBTENDO APENAS SDL JAVA COMPATIVEL COM SCARLETNX ($SDL_VERSION) ====="
  git -C "$SDL_SOURCES" fetch -q --depth 1 origin \
    "refs/tags/$SDL_VERSION:refs/tags/$SDL_VERSION" ||
    die "Nao foi possivel obter as classes Java SDL $SDL_VERSION"
  mkdir -p "$SDL_JAVA_CACHE"
  git -C "$SDL_SOURCES" archive "$SDL_VERSION" android-project/app/src/main/java |
    tar -xf - -C "$SDL_JAVA_CACHE" ||
    die "Nao foi possivel extrair as classes Java SDL $SDL_VERSION"
fi
grep -F 'native void nativeSetupJNI()' "$SDL_JAVA/org/libsdl/app/SDLActivity.java" >/dev/null ||
  die "A classe SDLActivity nao corresponde ao runtime ScarletNX"
export LASRECOMP_SNX_SDL_JAVA_DIR="$SDL_JAVA"
echo "SCARLETNX JNI: SDLActivity.nativeSetupJNI()V compatível"
echo "===== COMPILANDO E ASSINANDO APK COM SCARLETNX INTEGRADO ====="
bash compilar-lasrecomp-termux.sh
APK="$OUT/Zelda-SNX-Runtime-TESTE.apk"
[ -s "$APK" ] || die "APK final nao foi produzido"

# The main build script already verified and signed the completed archive;
# this second verification ensures the file delivered to Downloads is correct.
python3 - "$APK" "$SNX_CODE" "$CACHE" <<'PY'
import hashlib
import os
import sys
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path('tools').resolve()))
from scarletnx_elf_audit import audit
with zipfile.ZipFile(sys.argv[1]) as z:
    for n in ["lib/arm64-v8a/libscarletnx.so", "lib/arm64-v8a/libzelda_snx.so"]:
        f = z.getinfo(n)
        print("BIBLIOTECA INSTALAVEL:", n, f.file_size, "bytes")
        if f.file_size < 100000:
            raise SystemExit("ERRO: arquivo nativo pequeno ou ausente: " + n)
    # Additional integrity gate for the NativeAOT-only experimental build.
    # The .so is a general shader translator, never a bundle of private shaders.
    if os.environ.get('SCARLETNX_RYU_NATIVE_PROBE_BUILD') == '1':
        name = 'lib/arm64-v8a/libRyujinxShaderNative.so'
        packaged = z.read(name)
        native_source = Path(os.environ['SCARLETNX_RYU_NATIVE_SO'])
        if len(packaged) < 1024 * 1024:
            raise SystemExit('ERRO: tradutor nativo no APK esta vazio')
        if hashlib.sha256(packaged).digest() != hashlib.sha256(native_source.read_bytes()).digest():
            raise SystemExit('ERRO: NativeAOT mudou durante o empacotamento')
        print('SIGNED_APK_RYUJINX_NATIVE_ELF: OK,', len(packaged), 'bytes, shader packs: NENHUM')
    # Inspect the actual signed APK member, rather than assuming staging and
    # packaging used the same native runtime. Never alter the private AOT module.
    packaged = Path(sys.argv[3]) / 'signed-apk-libscarletnx.so'
    packaged.write_bytes(z.read('lib/arm64-v8a/libscarletnx.so'))
    report = audit(packaged, require_main=True, require_trace=True)
    if report['problems']:
        raise SystemExit('ELF final recusado: ' + '; '.join(report['problems']))
    with z.open('lib/arm64-v8a/libzelda_snx.so') as stream:
        aot_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    with open(sys.argv[2], 'rb') as stream:
        source_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if aot_digest != source_digest:
        raise SystemExit('ERRO: AOT Zelda foi alterado durante o empacotamento')
    print('SIGNED_APK_ELF_AUDIT: OK; AOT_SHA256_UNCHANGED:', aot_digest)
PY
mkdir -p /storage/emulated/0/Download/ZeldaRecomp
cp -f "$APK" /storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-Runtime-TESTE.apk
echo "===== APK SNX PRONTO ====="
echo "APK: /storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-Runtime-TESTE.apk"
echo "Tela: Zelda SNX Runtime — XCI source"
echo "Botao: Iniciar Zelda pelo ScarletNX"
echo "Teste real: o log deve conter SCARLETNX_MAIN_ENTERED. Sem esse marcador, main() nao foi comprovado."
echo "Se nao abrir, use Salvar log para capturar a tentativa atual."
