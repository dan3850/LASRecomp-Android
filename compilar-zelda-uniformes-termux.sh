#!/data/data/com.termux/files/usr/bin/bash
# Graphics uniform snapshots; retain the approved transfer optimization.
# Build a separate APK and leave Zelda-SNX-NXNATIVE-TRANSFER.apk untouched.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-NXNATIVE-TRANSFER.apk"
BACKUP="$FOLDER/Zelda-SNX-NXNATIVE-TRANSFER-ANTES-UNIFORMES.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_NXNATIVE=1 SCARLETNX_ZELDA_UNIFORM=1
export SCARLETNX_ZELDA_FSWZADD=0
bash "$ROOT/compilar-zelda-fps-audit-termux.sh"
python3 - "$FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    for asset in ('Zelda-NXNative.txt', 'Zelda-Uniforms.txt'):
        if z.read('assets/licenses/' + asset).decode().strip() != revision:
            raise SystemExit('ERRO: APK sem o perfil desta revisao: ' + asset)
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    if any(marker not in runtime for marker in (b'SNX_UNIFORM_META_V1', b'SNX_TRANSFER_META_V1', revision.encode())):
        raise SystemExit('ERRO: runtime sem uniformes/transferencias desta revisao')
print('SIGNED_APK_UNIFORM_SNAPSHOTS: OK')
PY
cp -p "$FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk" "$FOLDER/Zelda-SNX-UNIFORMES.apk"
echo "APK: $FOLDER/Zelda-SNX-UNIFORMES.apk"
echo "Uniformes em snapshots reutilizaveis: ON por padrao nesta variante (preferencia anterior respeitada)."
echo "Reutilizar buffers e agrupar transferencias: manter ON. Capturar shaders OFF; Registrar FPS LEVE."
echo "Compare apenas Uniformes OFF/ON, encerrando o jogo entre os testes; nao precisa recompilar."
echo "Referencia preservada: $REFERENCE (backup: $BACKUP, se ja havia APK)."
