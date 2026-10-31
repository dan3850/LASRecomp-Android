#!/data/data/com.termux/files/usr/bin/bash
# EXPERIMENTAL: repack existing Zelda TESTE with ScarletNX 2026 runtime.
# Never changes the original APK, game AOT module, source tree or cache.
set -euo pipefail
OLD="/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-Runtime-TESTE.apk"
NEW="$HOME/.cache/lasrecomp-scarletnx-upgrade/scarletnx-android-apk-2026/arm64-v8a/libscarletnx.so"
DEST="/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-2026-ABI-EXPERIMENTAL.apk"
REPORT="/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-2026-ABI-EXPERIMENTAL.txt"
NDK="$HOME/android-sdk/ndk/28.2.13676358"
TOOLS="$NDK/build-tools"
KEY="${SNX_SIGN_KEYSTORE:-$HOME/.android/debug.keystore}"
ALIAS="${SNX_SIGN_ALIAS:-androiddebugkey}"
PASS="${SNX_SIGN_PASSWORD:-android}"
die(){ echo "ERRO: $*" >&2; exit 1; }
for cmd in python3 unzip readelf zipalign apksigner keytool; do command -v "$cmd" >/dev/null || die "Falta $cmd (instale android-tools/openjdk-17 ou configure PATH)"; done
[ -s "$OLD" ] || die "APK original nao encontrada"
[ -s "$NEW" ] || die "Nucleo novo nao encontrado"
[ -s "$KEY" ] || die "Keystore ausente: $KEY. Configure SNX_SIGN_KEYSTORE, SNX_SIGN_ALIAS e SNX_SIGN_PASSWORD"
# Do not use grep -q on a large producer with pipefail: SIGPIPE produces a false failure.
python3 - "$NEW" "$OLD" <<'PY'
import subprocess,sys,zipfile
new,old=sys.argv[1:]
header=subprocess.check_output(["readelf","-h",new],text=True)
if "AArch64" not in header: raise SystemExit("ERRO: Nucleo novo nao ARM64")
symbols=subprocess.check_output(["readelf","-Ws",new],text=True)
if not any(line.split()[-1]=="JNI_OnLoad" for line in symbols.splitlines() if line.split()):
    raise SystemExit("ERRO: Nucleo sem JNI_OnLoad")
with zipfile.ZipFile(old) as z:
    for name in ("lib/arm64-v8a/libscarletnx.so","lib/arm64-v8a/libzelda_snx.so"):
        if name not in z.namelist(): raise SystemExit("ERRO: APK sem "+name)
print("ELF_JNI_ONLOAD_OK; APK_ZELDA_ORIGINAL_OK")
PY
# ABI 12 original versus 15 upstream: an ELF symbol alone cannot prove compatibility.
# Require an explicit acknowledgement to avoid presenting this as a validated update.
[ "${SNX_ALLOW_UNVERIFIED_ABI:-0}" = 1 ] || die "ABI 12 -> 15 ainda NAO comprovada. Para um teste experimental, execute: SNX_ALLOW_UNVERIFIED_ABI=1 bash $0"
TMP="$(mktemp -d "$HOME/.cache/zelda-snx-upgrade.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
python3 - "$OLD" "$NEW" "$TMP/unsigned.apk" <<'PY'
import sys,zipfile,pathlib
old,new,out=map(pathlib.Path,sys.argv[1:])
member="lib/arm64-v8a/libscarletnx.so"
with zipfile.ZipFile(old) as src, zipfile.ZipFile(out,"w",allowZip64=True) as dst:
    seen=set()
    for info in src.infolist():
        if info.filename in seen: raise SystemExit("ERRO: entrada duplicada: "+info.filename)
        seen.add(info.filename)
        if info.filename.startswith("META-INF/") and (info.filename.endswith((".RSA",".DSA",".EC",".SF")) or info.filename=="META-INF/MANIFEST.MF"):
            continue
        data=new.read_bytes() if info.filename==member else src.read(info.filename)
        dst.writestr(info,data)
PY
zipalign -f -p 4 "$TMP/unsigned.apk" "$TMP/aligned.apk"
apksigner sign --ks "$KEY" --ks-key-alias "$ALIAS" --ks-pass "pass:$PASS" --key-pass "pass:$PASS" --out "$TMP/signed.apk" "$TMP/aligned.apk"
apksigner verify --verbose "$TMP/signed.apk" >/dev/null || die "Assinatura nao passou"
python3 - "$TMP/signed.apk" "$NEW" "$OLD" <<'PY'
import hashlib,sys,zipfile
apk,new,old=sys.argv[1:]
with zipfile.ZipFile(apk) as z,zipfile.ZipFile(old) as previous:
    core=z.read("lib/arm64-v8a/libscarletnx.so")
    if hashlib.sha256(core).digest()!=hashlib.sha256(open(new,"rb").read()).digest():raise SystemExit("Nucleo divergente")
    if z.read("lib/arm64-v8a/libzelda_snx.so")!=previous.read("lib/arm64-v8a/libzelda_snx.so"):raise SystemExit("Modulo Zelda foi alterado")
print("APK_CONTENT_VERIFIED: runtime novo; modulo Zelda original preservado")
PY
cp "$TMP/signed.apk" "$DEST"
{ echo "APK_EXPERIMENTAL=$DEST"; echo "ABI_RUNTIME=2026 (compatibilidade Zelda nao comprovada)"; echo "APK original preservada: $OLD"; sha256sum "$NEW" "$DEST"; echo "Nao instalar sobre o aplicativo existente se a assinatura for diferente."; } > "$REPORT"
echo "APK_EXPERIMENTAL_GERADA=$DEST"
echo "RELATORIO=$REPORT"
echo "ATENCAO: apenas pacote assinado; boot Zelda ainda nao validado."
