#!/data/data/com.termux/files/usr/bin/bash
# Visual evidence only; preserve the last binding-profile APK and all caches.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
REFERENCE="$FOLDER/Zelda-SNX-BINDINGS.apk"
BACKUP="$FOLDER/Zelda-SNX-BINDINGS-ANTES-SOMBRAS.apk"
if [ -s "$REFERENCE" ] && [ ! -e "$BACKUP" ]; then cp -p "$REFERENCE" "$BACKUP"; fi
bash "$ROOT/compilar-zelda-bindings-termux.sh"
python3 - "$REFERENCE" "$(git rev-parse HEAD)" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    for marker in (b'SNX_SHADOW_CAPTURE_V1', b'SNX_SHADOW_DEPTH_V1', sys.argv[2].encode()):
        if marker not in runtime:
            raise SystemExit('ERRO: APK sem a captura de sombras desta revisao')
print('SIGNED_APK_VALIDATED_SHADOW_CAPTURE: OK')
PY
cp -p "$REFERENCE" "$FOLDER/Zelda-SNX-SOMBRAS.apk"
echo "APK: $FOLDER/Zelda-SNX-SOMBRAS.apk"
echo "Capturar sombras: OFF por padrao. Ative para um teste visual de 60 segundos na mesma cena."
echo "Exporte diagnostico de sombras (.zip); desligue a captura para comparar FPS."
echo "Nao altera shaders nem corrige automaticamente o efeito. AOT e caches reutilizados."
