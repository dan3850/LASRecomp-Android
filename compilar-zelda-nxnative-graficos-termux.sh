#!/data/data/com.termux/files/usr/bin/bash
# First graphics-backend slice: nxnative/Ryujinx buffer compute + Vulkan cache.
# Preserve all accepted runtime improvements, Stable60 and existing AOT/cache.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-COPIAS-ISOLADAS.apk"
BACKUP="$FOLDER/Zelda-SNX-COPIAS-ANTES-NXCOMPUTE.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_NX_COMPUTE=1
bash "$ROOT/compilar-zelda-copias-profundidade-termux.sh"
python3 - "$REFERENCE" "$(git rev-parse HEAD)" <<'PY'
import sys
import zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    if z.read('assets/licenses/Zelda-NXCompute.txt').decode().strip() != revision:
        raise SystemExit('ERRO: perfil compute nxnative de outra revisao')
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    for marker in (b'SNX_NX_COMPUTE_META_V1', b'SNX_NX_COMPUTE_STATS_V1',
                   b'nxnative-compute-v1', b'snx_ryu_translate_v1',
                   b'SNX_DEPTH_RANGE_META_V1', b'SNX_VB_POOL_META_V1', revision.encode()):
        if marker not in runtime:
            raise SystemExit('ERRO: APK sem o port compute/cache e a base grafica desta revisao')
    if 'lib/arm64-v8a/libRyujinxShaderNative.so' not in z.namelist():
        raise SystemExit('ERRO: biblioteca do tradutor nxnative/Ryujinx ausente')
print('SIGNED_APK_NXNATIVE_COMPUTE_CACHE: OK')
PY
cp -p "$REFERENCE" "$FOLDER/Zelda-SNX-NXNATIVE-COMPUTE.apk"
echo "APK: $FOLDER/Zelda-SNX-NXNATIVE-COMPUTE.apk"
echo "Compute nxnative/Ryujinx e seu cache iniciam ON, com controles independentes."
echo "Nesta comparacao, desligue Ryujinx Vulkan (fragmentos); altere somente Compute nxnative/Ryujinx."
echo "Preserve o estado das outras opcoes e do Stable60; capturas OFF e Registrar FPS LEVE."
echo "O log deve confirmar SNX_NX_COMPUTE_META_V1 ready=1 e shaders translated/cache_hits."
echo "A traducão de vertices/fragmentos e a renderizacao geral ainda usam a base existente."
