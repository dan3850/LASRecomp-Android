#!/data/data/com.termux/files/usr/bin/bash
# Incremental buffer-cache pool and passive write-watch evidence.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-BINDINGS.apk"
BACKUP="$FOLDER/Zelda-SNX-BINDINGS-ANTES-BUFFERS.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_VB_POOL=1
bash "$ROOT/compilar-zelda-bindings-termux.sh"
python3 - "$REFERENCE" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    if z.read('assets/licenses/Zelda-PersistentBuffers.txt').decode().strip() != revision:
        raise SystemExit('ERRO: APK sem o perfil de buffers desta revisao')
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    for marker in (b'SNX_VB_POOL_META_V1', b'SNX_WW_META_V1', b'SNX_WW_EVENT_V1', revision.encode()):
        if marker not in runtime:
            raise SystemExit('ERRO: runtime sem o pool/diagnostico desta revisao')
print('SIGNED_APK_VALIDATED_PERSISTENT_BUFFERS: OK')
PY
cp -p "$REFERENCE" "$FOLDER/Zelda-SNX-BUFFERS.apk"
echo "APK: $FOLDER/Zelda-SNX-BUFFERS.apk"
echo "Reutilizar buffers persistentes: ON neste perfil (preferencia anterior respeitada)."
echo "Compare OFF/ON em processos separados; mantenha as outras opcoes iguais."
echo "Capturar sombras OFF; Capturar shaders OFF; Registrar FPS LEVE."
echo "O log identifica falhas do rastreador; a politica de memoria nao foi alterada."
