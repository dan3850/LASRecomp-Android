#!/data/data/com.termux/files/usr/bin/bash
# Incremental packed D24/S8 export; preserve current visual/performance options.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-EFEITOS-DEPTH-DIAG.apk"
BACKUP="$FOLDER/Zelda-SNX-COPIAS-V1-ANTES-ISOLADAS.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_D24_COPIES=1
bash "$ROOT/compilar-zelda-efeitos-termux.sh"
python3 - "$REFERENCE" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    if z.read('assets/licenses/Zelda-D24Copies.txt').decode().strip() != revision:
        raise SystemExit('ERRO: APK sem o perfil de copias desta revisao')
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    for marker in (b'SNX_D24_PACK_META_V1', b'SNX_D24_PACK_V1', b'SNX_D24_PACK_STATE_V1',
                   b'"integration":2,"gpu_overlay_only":1,"cpu_writeback":0,"isolated_work":1',
                   b'SNX_EFFECT_DEPTH_PAIR_V1', b'SNX_DEPTH_RANGE_META_V1', b'SNX_VB_POOL_META_V1', revision.encode()):
        if marker not in runtime:
            raise SystemExit('ERRO: runtime sem as copias/diagnostico desta revisao')
print('SIGNED_APK_VALIDATED_D24_COPIES: OK')
PY
cp -p "$REFERENCE" "$FOLDER/Zelda-SNX-COPIAS-ISOLADAS.apk"
echo "APK: $FOLDER/Zelda-SNX-COPIAS-ISOLADAS.apk"
echo "Copias D24 isoladas (teste) inicia OFF, sem herdar o ON da versao que regrediu."
echo "Preservar faixa de profundidade ON; para validar a correcao isolada, altere apenas Copias D24 isoladas para ON."
echo "O log confirma se o shader interno atualizado habilitou a correcao."
echo "Comparacao: altere so Copias D24 isoladas OFF/ON, sempre iniciando outro processo."
echo "O ZIP anterior ja confirmou os pixels. Neste teste, mantenha todas as capturas OFF."
echo "Para jogar/medir: todas as capturas OFF e Registrar FPS LEVE."
