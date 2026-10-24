#!/data/data/com.termux/files/usr/bin/bash
# Passive composition evidence; retain the improved depth/performance reference.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-PROFUNDIDADE.apk"
BACKUP="$FOLDER/Zelda-SNX-PROFUNDIDADE-ANTES-ILUMINACAO.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_LIGHT_DIAG=1
bash "$ROOT/compilar-zelda-profundidade-termux.sh"
python3 - "$REFERENCE" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    if z.read('assets/licenses/Zelda-LightDiagnostics.txt').decode().strip() != revision:
        raise SystemExit('ERRO: APK sem o perfil de diagnostico desta revisao')
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    for marker in (b'SNX_LIGHT_META_V1', b'SNX_LIGHT_STATE_V1', b'SNX_LIGHT_RT_V1',
                   b'SNX_LIGHT_V1', b'SNX_DEPTH_RANGE_META_V1', b'SNX_VB_POOL_META_V1', revision.encode()):
        if marker not in runtime:
            raise SystemExit('ERRO: runtime sem o diagnostico/correcoes desta revisao')
print('SIGNED_APK_VALIDATED_LIGHT_DIAGNOSTICS: OK')
PY
cp -p "$REFERENCE" "$FOLDER/Zelda-SNX-ILUMINACAO-DIAG.apk"
echo "APK: $FOLDER/Zelda-SNX-ILUMINACAO-DIAG.apk"
echo "Diagnostico de composicao: selecione Registrar FPS GPU DETALHADA."
echo "Mantenha Preservar faixa de profundidade ON e as opcoes de desempenho atuais."
echo "Capturas de shaders e sombras OFF; exporte um log na casa e outro na nevoa externa."
echo "Depois do diagnostico, volte o registro para LEVE."
