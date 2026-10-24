#!/data/data/com.termux/files/usr/bin/bash
# Incremental visual-correctness trial; retain all performance ports and AOT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-BUFFERS.apk"
BACKUP="$FOLDER/Zelda-SNX-BUFFERS-ANTES-PROFUNDIDADE.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_DEPTH_RANGE=1
bash "$ROOT/compilar-zelda-buffers-termux.sh"
python3 - "$REFERENCE" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    if z.read('assets/licenses/Zelda-DepthRange.txt').decode().strip() != revision:
        raise SystemExit('ERRO: APK sem o perfil de profundidade desta revisao')
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    for marker in (b'SNX_DEPTH_RANGE_META_V1', b'SNX_DEPTH_RANGE_STATE_V1',
                   b'SNX_DEPTH_RANGE_V1', b'VK_EXT_depth_range_unrestricted',
                   b'SNX_VB_POOL_META_V1', revision.encode()):
        if marker not in runtime:
            raise SystemExit('ERRO: runtime sem a correcao/diagnostico desta revisao')
print('SIGNED_APK_VALIDATED_DEPTH_RANGE: OK')
PY
cp -p "$REFERENCE" "$FOLDER/Zelda-SNX-PROFUNDIDADE.apk"
echo "APK: $FOLDER/Zelda-SNX-PROFUNDIDADE.apk"
echo "Preservar faixa de profundidade: ON neste perfil (preferencia anterior respeitada)."
echo "O log confirma o suporte do driver e se a correcao foi ativada."
echo "Compare OFF/ON no mesmo local, com processos separados e outras opcoes iguais."
echo "Capturar shaders OFF; Capturar sombras OFF; Registrar FPS LEVE."
