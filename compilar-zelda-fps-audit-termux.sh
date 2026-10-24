#!/data/data/com.termux/files/usr/bin/bash
# Runtime-only audit build. Reuse Stable60 AOT and all build caches.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
test "$(git branch --show-current)" = experimental/zelda-links-awakening-ryujinx-nativeaot || {
  echo "ERRO: selecione a branch experimental do Zelda" >&2; exit 1;
}
export SCARLETNX_TEST_SRC="${SCARLETNX_TEST_SRC:-$HOME/.cache/lasrecomp-scarletnx-romfs/ScarletNX}"
# Phone feedback: the operand repair did not restore the missing effects.
# Return to the earlier arithmetic/cache by default; retain an explicit A/B opt-in.
export SCARLETNX_ZELDA_FSWZADD="${SCARLETNX_ZELDA_FSWZADD:-0}"
case "$SCARLETNX_ZELDA_FSWZADD" in 0|1) ;; *) echo "ERRO: SCARLETNX_ZELDA_FSWZADD deve ser 0 ou 1" >&2; exit 1 ;; esac
python3 -m unittest discover -s tests -p 'test_zelda_perf*.py'
FOLDER=/storage/emulated/0/Download/ZeldaRecomp
GOOD="$FOLDER/Zelda-SNX-Runtime-STABLE60-TOGGLE-TESTE.apk"
BACKUP="$FOLDER/Zelda-SNX-STABLE60-ANTES-FPS-AUDIT.apk"
if [ -s "$GOOD" ] && [ ! -e "$BACKUP" ]; then cp -p "$GOOD" "$BACKUP"; fi
BEFORE_BASELINE="$FOLDER/Zelda-SNX-STABLE60-ANTES-BASELINE.apk"
if [ "$SCARLETNX_ZELDA_FSWZADD" = 0 ] && [ -s "$GOOD" ] && [ ! -e "$BEFORE_BASELINE" ]; then
  cp -p "$GOOD" "$BEFORE_BASELINE"
fi
BEFORE_FSWZ="$FOLDER/Zelda-SNX-STABLE60-ANTES-FSWZADD.apk"
if [ "$SCARLETNX_ZELDA_FSWZADD" = 1 ] && [ -s "$GOOD" ] && [ ! -e "$BEFORE_FSWZ" ]; then
  cp -p "$GOOD" "$BEFORE_FSWZ"
fi
export SCARLETNX_ZELDA_PERF=1 SCARLETNX_RYU_V2=0
bash "$ROOT/compilar-zelda-stable60-toggle-termux.sh"
python3 - "$GOOD" "$(git rev-parse HEAD)" "$SCARLETNX_ZELDA_FSWZADD" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    runtime = z.read('lib/arm64-v8a/libscarletnx.so')
    if any(marker not in runtime for marker in [b'SNX_PERF_META_V1', b'SNX_GFX_BIND_V1', b'SNX_SHADER_CAPTURE_V1', b'SNX_RYU_CACHE_V1', b'SNX_HASH_SPAN_META_V1',
                                               b'SNX_KNOWN_COMPLETE_V1', b'SNX_TRANSFER_META_V1', b'SNX_UNIFORM_META_V1', sys.argv[2].encode()]):
        raise SystemExit('ERRO: APK nao contem o runtime de medicao desta revisao')
    if (b'SNX_FSWZADD_V1' in runtime) != (sys.argv[3] == '1'):
        raise SystemExit('ERRO: APK nao corresponde ao modo FSWZADD solicitado')
    if z.read('assets/licenses/Zelda-PERF.txt').decode().strip() != sys.argv[2]:
        raise SystemExit('ERRO: marcador de medicao desatualizado')
print('SIGNED_APK_PERF_RUNTIME: OK')
PY
cp -p "$GOOD" "$FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk"
echo "APK: $FOLDER/Zelda-SNX-STABLE60-FPS-AUDIT.apk"
echo "FSWZADD operandos/sinais corrigidos: $SCARLETNX_ZELDA_FSWZADD (1=teste, 0=comparacao anterior)"
echo "Antes da correcao: $BEFORE_FSWZ (se ja havia um APK)"
echo "Antes do retorno a base: $BEFORE_BASELINE (se ja havia um APK)"
echo "Registrar FPS no log > LEVE para desempenho; GPU DETALHADA para sombras/texturas."
echo "Para comparar FPS: Capturar shaders OFF, Registrar FPS LEVE; encerre e abra o jogo."
echo "Verificacao de texturas por faixa: compare OFF/ON no mesmo APK, em execucoes separadas."
echo "Home > Stable 60 FPS: mesmo estado em cada teste."
echo "Jogue 90 segundos na mesma cena e use Salvar log. Nao desinstale o app."
