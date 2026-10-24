#!/data/data/com.termux/files/usr/bin/bash
# New-pass full clears as load actions; retain approved transfers and uniforms.
# Keep the prior uniform and transfer APKs available for reversal.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-UNIFORMES.apk"
BACKUP="$FOLDER/Zelda-SNX-UNIFORMES-ANTES-CLEARS.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
export SCARLETNX_ZELDA_NXNATIVE=1 SCARLETNX_ZELDA_UNIFORM=1 SCARLETNX_ZELDA_CLEAR_LOAD=1
export SCARLETNX_ZELDA_FSWZADD=0
bash "$ROOT/compilar-zelda-fps-audit-termux.sh"
python3 - "$FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    revision = sys.argv[2]
    for asset in ('Zelda-NXNative.txt', 'Zelda-Uniforms.txt', 'Zelda-Clears.txt'):
        if z.read('assets/licenses/' + asset).decode().strip() != revision:
            raise SystemExit('ERRO: APK sem o perfil desta revisao: ' + asset)
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    markers = (b'SNX_CLEAR_LOAD_META_V1', b'SNX_UNIFORM_META_V1', b'SNX_TRANSFER_META_V1', revision.encode())
    if any(marker not in runtime for marker in markers):
        raise SystemExit('ERRO: runtime sem clears/uniformes/transferencias desta revisao')
print('SIGNED_APK_FULL_CLEAR_LOADS: OK')
PY
cp -p "$FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk" "$FOLDER/Zelda-SNX-CLEARS.apk"
echo "APK: $FOLDER/Zelda-SNX-CLEARS.apk"
echo "Limpezas completas no inicio do passe: ON por padrao nesta variante (preferencia anterior respeitada)."
echo "Uniformes e reutilizacao de transferencias: manter ON. Capturar shaders OFF; Registrar FPS LEVE."
echo "Compare apenas Limpezas OFF/ON, encerrando o jogo entre os testes; nao precisa recompilar."
echo "Referencia preservada: $REFERENCE (backup: $BACKUP, se ja havia APK)."
