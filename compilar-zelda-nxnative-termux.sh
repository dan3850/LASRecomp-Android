#!/data/data/com.termux/files/usr/bin/bash
# Persistent Vulkan transfers, grouped copies and full linear DMA overwrites.
# Reuses the current game AOT and shader/build caches.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export SCARLETNX_ZELDA_NXNATIVE=1
export SCARLETNX_ZELDA_FSWZADD=0
bash "$ROOT/compilar-zelda-fps-audit-termux.sh"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
python3 - "$FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    if z.read('assets/licenses/Zelda-NXNative.txt').decode().strip() != revision:
        raise SystemExit('ERRO: APK sem o perfil de transferencias desta revisao')
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    if b'SNX_TRANSFER_META_V1' not in runtime or revision.encode() not in runtime:
        raise SystemExit('ERRO: runtime sem as transferencias desta revisao')
print('SIGNED_APK_NXNATIVE_TRANSFERS: OK')
PY
cp -p "$FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk" "$FOLDER/Zelda-SNX-NXNATIVE-TRANSFER.apk"
echo "APK: $FOLDER/Zelda-SNX-NXNATIVE-TRANSFER.apk"
echo "Reutilizar buffers e agrupar transferencias: ON por padrao nesta variante (preferencia anterior respeitada)."
echo "Capturar shaders OFF; Registrar FPS LEVE. Instale como atualizacao."
