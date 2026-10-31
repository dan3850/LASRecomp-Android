#!/data/data/com.termux/files/usr/bin/bash
# Prepare Android-extractable ELF names in a separate 2026 staging directory.
# Never change the compiled originals or Termux libraries.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$HOME/.cache/lasrecomp-scarletnx-upgrade/output/apk-libs/arm64-v8a"
DST="$HOME/.cache/lasrecomp-scarletnx-upgrade/output/android-ready/arm64-v8a"
command -v patchelf >/dev/null || { echo "ERRO: patchelf ausente"; exit 1; }
[ -s "$SRC/libscarletnx.so" ] || { echo "ERRO: libscarletnx.so ausente"; exit 1; }
mkdir -p "$DST"
# Copy only known libraries; no wildcard copying from Termux.
for name in libscarletnx.so libLLVM.so libc++_shared.so libffi.so libiconv.so libxml2.so.16 libz.so.1 libzstd.so.1; do
  [ -s "$SRC/$name" ] || { echo "ERRO: $name ausente"; exit 1; }
  cp -L "$SRC/$name" "$DST/$name"
done
# Android PackageManager extracts lib*.so entries. Normalize versioned ELF
# names AND every DT_NEEDED reference to the corresponding new SONAME.
for old in libxml2.so.16 libzstd.so.1; do
  new="${old%%.so.*}.so"
  mv "$DST/$old" "$DST/$new"
  patchelf --set-soname "$new" "$DST/$new"
  for lib in "$DST"/*.so; do
    if readelf -d "$lib" | grep -F "Shared library: [$old]" >/dev/null; then
      patchelf --replace-needed "$old" "$new" "$lib"
    fi
  done
done
# Prefer Android's system zlib, not a Termux libz.so.1 copied into the APK.
for lib in "$DST"/*.so; do
  if readelf -d "$lib" | grep -F 'Shared library: [libz.so.1]' >/dev/null; then
    patchelf --replace-needed libz.so.1 libz.so "$lib"
  fi
done
rm -f "$DST/libz.so.1"
for lib in "$DST"/*.so; do
  patchelf --remove-rpath "$lib"
done
python3 - "$DST" <<'PY'
import pathlib, re, subprocess, sys
folder = pathlib.Path(sys.argv[1])
system = set("libc.so libm.so libdl.so liblog.so libandroid.so libz.so libvulkan.so libEGL.so libGLESv1_CM.so libGLESv2.so libGLESv3.so libOpenSLES.so libaaudio.so libmediandk.so libjnigraphics.so libstdc++.so".split())
errors = []
for lib in sorted(folder.glob("*.so")):
    head = subprocess.check_output(["readelf","-h",str(lib)],text=True)
    dyn = subprocess.check_output(["readelf","-d",str(lib)],text=True)
    if "AArch64" not in head: errors.append(f"{lib.name}: not ARM64")
    sn = re.findall(r"\(SONAME\).*?\[([^]]+)\]",dyn)
    if not sn or sn[0] != lib.name: errors.append(f"{lib.name}: SONAME mismatch")
    if "RPATH" in dyn or "RUNPATH" in dyn: errors.append(f"{lib.name}: runtime path")
    for needed in re.findall(r"\(NEEDED\).*?\[([^]]+)\]",dyn):
        if needed not in system and not (folder/needed).is_file():
            errors.append(f"{lib.name}: missing {needed}")
if errors: raise SystemExit("\n".join(errors))
print("ANDROID_ELF_STAGING_OK:", folder)
print("APK_ZELDA_2026_READY=NO (missing Zelda AOT module and JNI integration)")
PY
