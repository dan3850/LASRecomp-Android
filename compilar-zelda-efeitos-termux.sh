#!/data/data/com.termux/files/usr/bin/bash
# Bounded scene-depth pairs; preserve the improved lighting/performance build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-ILUMINACAO-DIAG.apk"
BACKUP="$FOLDER/Zelda-SNX-ILUMINACAO-ANTES-EFEITOS.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_EFFECT_DEPTH=1
bash "$ROOT/compilar-zelda-iluminacao-termux.sh"
python3 - "$REFERENCE" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    if z.read('assets/licenses/Zelda-EffectDepth.txt').decode().strip() != revision:
        raise SystemExit('ERRO: APK sem o perfil pareado desta revisao')
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    for marker in (b'SNX_EFFECT_DEPTH_CAPTURE_V1', b'SNX_EFFECT_DEPTH_PAIR_V1', b'SNX_COLOR_PROBE_V1',
                   b'SNX_DEPTH_RANGE_META_V1', b'SNX_VB_POOL_META_V1', revision.encode()):
        if marker not in runtime:
            raise SystemExit('ERRO: runtime sem o diagnostico/correcoes desta revisao')
print('SIGNED_APK_VALIDATED_EFFECT_DEPTH: OK')
PY
cp -p "$REFERENCE" "$FOLDER/Zelda-SNX-EFEITOS-DEPTH-DIAG.apk"
echo "APK: $FOLDER/Zelda-SNX-EFEITOS-DEPTH-DIAG.apk"
echo "Capturar profundidade de luz/nevoa ON; capturas de sombras/shaders OFF; Registrar FPS LEVE."
echo "Interaja com o telefone/NPC perto de 15, 30 e 45 segundos; saia e exporte o ZIP de efeitos."
echo "O log agora inclui SNX_COLOR_PROBE_V1: brilho HDR apos cena, desfoque e composicao."
echo "Depois desligue a captura e inicie outro processo para jogar normalmente."
