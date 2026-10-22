#!/usr/bin/env bash
# CI-only: fresh native runtime + matching NativeAOT, then the existing launcher.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
: "${SCARLETNX_SRC:?}" "${RYU_OUTPUT:?}" "${RYU_STAGE:?}" "${ANDROID_NDK_ROOT:?}" "${GITHUB_SHA:?}"
OUT="$ROOT/build/scarletnx-graphics"
BUILD="$OUT/native"
STAGE="$OUT/app"
mkdir -p "$STAGE/src/main/java/com/retroaura/lasrecomp" "$STAGE/src/main/jniLibs/arm64-v8a" "$STAGE/src/main/assets"
python3 "$ROOT/tools/ryujinx-nativeaot/patch_runtime_v2.py" "$SCARLETNX_SRC" \
  --identity "$RYU_STAGE/build-identity.json" --revision "$GITHUB_SHA"
python3 "$ROOT/tools/patch_scarletnx_romfs.py" "$SCARLETNX_SRC"
python3 "$ROOT/tools/patch_scarletnx_fswzadd.py" "$SCARLETNX_SRC"
python3 "$ROOT/tools/ryujinx-nativeaot/patch_host1x_relocations.py" "$SCARLETNX_SRC"
cmake -S "$SCARLETNX_SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 -DANDROID_STL=c++_shared \
  -DLLVM_DIR="$LLVM_PREFIX/lib/cmake/llvm" -DSNX_DEPLOY=OFF -DSNX_BUILD_GNUABI=OFF \
  -DSNX_BUILD_3DS=OFF -DSNX_BUILD_GUI=OFF -DBUILD_TESTING=OFF -DSNX_OPT_FLAGS='-O2 -g0' \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache
cmake --build "$BUILD" --parallel 2
SO="$(find "$BUILD" -name libscarletnx.so -print -quit)"
test -s "$SO"
LIBS="$STAGE/src/main/jniLibs/arm64-v8a"
cp "$SO" "$LIBS/libscarletnx.so"
cp "$RYU_OUTPUT/libRyujinxShaderNative.so" "$LIBS/"
cp "$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so" "$LIBS/"
READELF="$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
"$READELF" -h "$LIBS/libscarletnx.so" | tee "$OUT/runtime-elf.txt"
"$READELF" -Ws "$LIBS/libRyujinxShaderNative.so" > "$OUT/nativeaot-exports.txt"
for symbol in snx_ryu_translate_scarlet_v2 snx_ryu_build_identity snx_ryu_free_v1; do
  grep -F "$symbol" "$OUT/nativeaot-exports.txt" > /dev/null
done
# Never substitute SDL Java from a different native SDL version.
SDL_ACTIVITY="$(find "$SCARLETNX_SRC/.cache/cpm" -path '*/android-project/app/src/main/java/org/libsdl/app/SDLActivity.java' -print -quit)"
test -s "$SDL_ACTIVITY"
grep -F 'native void nativeSetupJNI()' "$SDL_ACTIVITY" > /dev/null
mkdir -p "$STAGE/src/main/java/org/libsdl"
cp -R "$(dirname "$SDL_ACTIVITY")" "$STAGE/src/main/java/org/libsdl/app"
for source in CastlevaniaSnxBootActivity MarioSnxGameActivity ScarletNxLogReport; do
  cp "$ROOT/android/src/com/retroaura/lasrecomp/$source.java" "$STAGE/src/main/java/com/retroaura/lasrecomp/"
done
export STAGE ROOT
python3 - <<'PY'
import hashlib, json, os, pathlib, xml.etree.ElementTree as ET
root, stage = pathlib.Path(os.environ['ROOT']), pathlib.Path(os.environ['STAGE'])
ns = 'http://schemas.android.com/apk/res/android'; ET.register_namespace('android', ns)
tree = ET.parse(root/'android/castlevania/AndroidManifest.xml'); manifest = tree.getroot(); manifest.attrib.pop('package', None)
for activity in list(manifest.find('application').findall('activity')):
    if activity.get('{'+ns+'}name', '').endswith('.GameSDLActivity'): manifest.find('application').remove(activity)
manifest.find('application').set('{'+ns+'}label', 'Castlevania SNX Graphics')
tree.write(stage/'src/main/AndroidManifest.xml', encoding='utf-8', xml_declaration=True)
metadata = json.loads((pathlib.Path(os.environ['RYU_STAGE'])/'build-identity.json').read_text())
metadata.update(commit=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'],
    scarletnx='34853eeae5af132e320adbb0193f13344085bf89', nxnative='1eaaab88caffcc17ada94b6dbdbe4f3b02fbb480',
    libraries={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (stage/'src/main/jniLibs/arm64-v8a').glob('*.so')})
for p in (stage/'src/main/jniLibs/arm64-v8a').glob('*.so'):
    data = p.read_bytes()
    assert data[:6] == b'\x7fELF\x02\x01' and data[18:20] == b'\xb7\0', p
    if p.name == 'libscarletnx.so': assert os.environ['GITHUB_SHA'].encode() in data, 'stale runtime revision'
    if p.name != 'libc++_shared.so': assert metadata['source_identity'].encode() in data, 'stale adapter identity'
(stage/'src/main/assets/graphics-build.json').write_text(json.dumps(metadata, indent=2)+'\n')
PY
cp "$SCARLETNX_SRC/LICENSE" "$STAGE/src/main/assets/ScarletNX-LICENSE.txt"
cp "$ROOT/LICENSE" "$STAGE/src/main/assets/LASRecomp-LICENSE.txt"
cat > "$STAGE/settings.gradle" <<'GRADLE'
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = 'ScarletNXGraphics'
GRADLE
cat > "$STAGE/build.gradle" <<'GRADLE'
plugins { id 'com.android.application' version '8.10.1' }
android {
    namespace = 'com.retroaura.lasrecomp'
    compileSdk = 35
    defaultConfig {
        applicationId = 'com.retroaura.castlevania.snxruntime.graphics'
        minSdk = 26
        targetSdk = 35
        versionCode = System.getenv('GITHUB_RUN_NUMBER').toInteger()
        versionName = 'graphics-' + System.getenv('GITHUB_SHA').substring(0, 12)
    }
    compileOptions { sourceCompatibility JavaVersion.VERSION_1_8; targetCompatibility JavaVersion.VERSION_1_8 }
    packaging.jniLibs { useLegacyPackaging = true; keepDebugSymbols += ['**/*.so'] }
}
GRADLE
gradle --no-daemon -p "$STAGE" assembleDebug
APK="$OUT/ScarletNX-Castlevania-ARM64-${GITHUB_SHA:0:12}.apk"
cp "$STAGE/build/outputs/apk/debug/app-debug.apk" "$APK"
export APK
python3 - <<'PY'
import hashlib, json, os, pathlib, zipfile
stage = pathlib.Path(os.environ['STAGE'])
meta = json.loads((stage/'src/main/assets/graphics-build.json').read_text())
with zipfile.ZipFile(os.environ['APK']) as z:
    for name, digest in meta['libraries'].items():
        assert hashlib.sha256(z.read('lib/arm64-v8a/'+name)).hexdigest() == digest, 'APK library mismatch: '+name
    assert not any('castlevania_snx.so' in n or '_code.so' in n or n.endswith('.keys') for n in z.namelist())
print('SIGNED_APK_IDENTITY_OK:', meta['commit'], meta['source_identity'])
PY
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose --print-certs "$APK"
cp "$STAGE/src/main/assets/graphics-build.json" "$OUT/"
git -C "$SCARLETNX_SRC" diff --binary > "$OUT/scarletnx-changes.patch"
# Include exact modified upstream source, without dependency/build caches.
tar -C "$SCARLETNX_SRC" --exclude=.git --exclude=.cache --exclude=build -czf "$OUT/ScarletNX-source.tar.gz" .
git -C "$ROOT" archive --format=zip --prefix=LASRecomp-Android/ HEAD > "$OUT/LASRecomp-Android-source.zip"
(cd "$OUT" && sha256sum *.apk > APK-SHA256SUMS)
printf 'APK ready: %s\n' "$APK"
