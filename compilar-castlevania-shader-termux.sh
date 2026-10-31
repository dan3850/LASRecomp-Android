#!/data/data/com.termux/files/usr/bin/bash
# Experimental Castlevania FSWZADD 0xD7 repair (incremental).
# Reuse pinned ScarletNX source/CMake/Ninja cache; preserve Mario runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
BRANCH="$(git branch --show-current)"
if [ "$BRANCH" != experimental/castlevania-belmonts-curse ] &&
   [ "$BRANCH" != experimental/ryujinx-runtime-nativeaot ] &&
   [ "$BRANCH" != experimental/zelda-links-awakening-ryujinx-nativeaot ]; then
  echo "ERRO: branch experimental do Castlevania ou Ryujinx NativeAOT necessaria" >&2
  exit 1
fi
SRC="$HOME/.cache/lasrecomp-scarletnx-romfs/ScarletNX"
OUT="$HOME/scarletnx-zelda-shader-build/libscarletnx.so"
# The source cache is shared with other builds. Restore it quietly, but never
# hide the original build failure or silently ignore a failed restoration.
restore_source() {
  local rc="$1" restore_failed=0
  trap - EXIT
  if [ -f "$SRC/src/nx/gpu/vk/snx_nx_compute.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_nx_compute.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando compute/cache nxnative" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_d24_pack.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_d24_pack.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando copias D24" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_effect_depth.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_effect_depth.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando captura pareada de profundidade" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_lighting_diag.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_lighting_diag.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando diagnostico de iluminacao" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_depth_range.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_depth_range.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando faixa de profundidade Vulkan" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_vb_pool.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_vb_pool.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando pool de buffers persistentes" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/runtime/platform/snx_ww_diag.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_ww_diag.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando diagnostico de memoria alterada" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_shadow_capture.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_shadow_capture.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando captura de profundidade das sombras" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_bind_reuse.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_bind_reuse.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando reutilizacao dos bindings validados" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_ub_extent.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_ub_extent.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando alcance comprovado dos uniformes" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_clear_load.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_clear_load.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando limpezas iniciais dos passes" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_uniform.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_uniform.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando snapshots de uniformes" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_transfer.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_transfer.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando transferencias Vulkan" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/snx_hash_span.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_hash_span.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando a verificacao de texturas por faixa" >&2
      restore_failed=1
    fi
  fi
  if [ -f "$SRC/src/nx/gpu/vk/pipeline.c" ] &&
     grep -qF SNX_FSWZADD_V1 "$SRC/src/nx/gpu/vk/pipeline.c"; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_fswz.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando a correcao FSWZADD/cache do Zelda" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_ZELDA_PERF:-0}" = 1 ] &&
     [ -f "$SRC/src/nx/gpu/vk/snx_ryu_cache.h" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_perf_opt.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando experiencias de desempenho" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_ZELDA_PERF:-0}" = 1 ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_perf.py" "$SRC" --revert; then
      echo "ERRO: falha restaurando instrumentacao de desempenho" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_RYU_V2:-0}" = 1 ] &&
     [ -s "$SRC/src/nx/runtime/guest_jit.c" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_jit_cache.py" "$SRC" --revert; then
      echo "AVISO: falha restaurando a politica do cache JIT no cache de fontes" >&2
      restore_failed=1
    fi
  fi
  if [ -s "$SRC/src/nx/gpu/shader/spirv_translate.c" ]; then
    if [ "${SCARLETNX_ZELDA_SHADER_WINDOW:-0}" = 1 ]; then
      if ! python3 "$ROOT/tools/patch_scarletnx_zelda_shader_window.py" "$SRC" --revert; then
        echo "ERRO: falha restaurando shader window" >&2
        restore_failed=1
      fi
    fi
    if [ "${SCARLETNX_ZELDA_SHFL_FIX:-0}" = 1 ]; then
      if ! python3 "$ROOT/tools/patch_scarletnx_zelda_shfl_predicate.py" "$SRC" --revert; then
        echo "ERRO: falha restaurando SHFL predicate" >&2
        restore_failed=1
      fi
    fi
    if [ "${SCARLETNX_ZELDA_CONDITIONAL_EXIT:-0}" = 1 ]; then
      if ! python3 "$ROOT/tools/patch_scarletnx_zelda_conditional_exit.py" "$SRC" --revert; then
        echo "ERRO: falha restaurando conditional EXIT" >&2
        restore_failed=1
      fi
    fi
    if ! python3 "$ROOT/tools/patch_scarletnx_bindless_diag.py" "$SRC" --revert >/dev/null; then
      echo "AVISO: nao foi possivel restaurar o diagnostico bindless no cache." >&2
      restore_failed=1
    fi
    if ! python3 "$ROOT/tools/patch_scarletnx_fswzadd.py" "$SRC" --revert >/dev/null; then
      echo "AVISO: nao foi possivel restaurar o patch FSWZADD no cache." >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_RYUJINX_BRIDGE:-0}" = 1 ] &&
     [ -s "$SRC/src/nx/gpu/vk/pipeline.c" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_ryujinx_runtime.py" "$SRC" --revert; then
      echo "AVISO: falha restaurando pipeline Vulkan Ryujinx experimental" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_RYU_NATIVE_PROBE_BUILD:-0}" = 1 ] &&
     [ -s "$SRC/src/nx/gpu/video/host1x.c" ]; then
    if ! python3 "$ROOT/tools/ryujinx-nativeaot/patch_host1x_relocations.py" "$SRC" --revert; then
      echo "AVISO: falha restaurando Host1x no cache" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_RYU_NATIVE_PROBE_BUILD:-0}" = 1 ] &&
     [ -s "$SRC/src/nx/gpu/vk/pipeline.c" ]; then
    local restore_tool="$ROOT/tools/ryujinx-nativeaot/patch_scarletnx_live_probe.py"
    if [ "${SCARLETNX_RYU_V2:-0}" = 1 ]; then restore_tool="$ROOT/tools/termux_ryujinx_v2.py"; fi
    if ! python3 "$restore_tool" "$SRC" --revert; then
      echo "AVISO: falha restaurando Ryujinx NativeAOT live probe no cache" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_ZELDA_DEJAVU_FONT:-0}" = 1 ] &&
     [ -f "$SRC/cmake/shared_fonts.cmake" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda_fonts.py" "$SRC" --revert; then
      echo "AVISO: nao consegui restaurar as fontes originais no cache ScarletNX" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_ZELDA60_TOGGLE:-0}" = 1 ] &&
     [ -f "$SRC/src/nx/runtime/main.c" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda60_toggle.py" "$SRC" --mode runtime --revert; then
      echo "AVISO: nao consegui restaurar o toggle Zelda60 no cache ScarletNX" >&2
      restore_failed=1
    fi
  fi
  if [ "${SCARLETNX_ZELDA_60FPS_DIAG:-0}" = 1 ] &&
     [ -f "$SRC/src/nx/runtime/main.c" ]; then
    if ! python3 "$ROOT/tools/patch_scarletnx_zelda60_diag.py" "$SRC" --revert; then
      echo "AVISO: nao consegui restaurar diagnostico Zelda60 no cache fonte" >&2
      restore_failed=1
    fi
  fi
  if [ "$rc" -ne 0 ]; then
    echo "ERRO: compilacao experimental falhou (codigo $rc). Veja a primeira mensagem ERRO acima." >&2
  elif [ "$restore_failed" -ne 0 ]; then
    echo "AVISO: APK gerado, mas o cache ScarletNX precisa de revisao antes de outro build." >&2
  fi
  if [ "$rc" -eq 0 ] && [ "$restore_failed" -ne 0 ]; then rc=1; fi
  exit "$rc"
}
trap 'restore_source "$?"' EXIT
python3 tests/test_castlevania_shader_patch.py
python3 tests/test_castlevania_bindless_diag.py
if [ "${SCARLETNX_RYU_NATIVE_PROBE_BUILD:-0}" = 1 ]; then
  python3 -m unittest discover -s tests -p 'test_ryujinx_live_probe_patch.py'
fi
if [ "${SCARLETNX_RYUJINX_BRIDGE:-0}" = 1 ]; then
  python3 tests/test_castlevania_ryujinx_runtime_patch.py
  python3 -m unittest discover -s tests -p 'test_ryujinx_spirv_bridge.py'
fi
# Keep the known booting but graphically incomplete test APK for comparison.
OLD_APK="/storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-Runtime-TESTE.apk"
BACKUP="/storage/emulated/0/Download/ZeldaRecomp/Castlevania-SNX-Runtime-ANTES-FSWZADD.apk"
if [ -s "$OLD_APK" ] && [ ! -e "$BACKUP" ]; then
  cp -p "$OLD_APK" "$BACKUP"
  echo "APK experimental anterior preservado em: $BACKUP"
fi
if [ ! -s "$SRC/src/nx/gpu/shader/spirv_translate.c" ]; then
  echo "ERRO: fonte ScarletNX nao encontrado no cache; rode primeiro o build normal." >&2
  exit 1
fi
python3 "$ROOT/tools/patch_scarletnx_bindless_diag.py" "$SRC"
if [ "${SCARLETNX_ZELDA_SHFL_FIX:-0}" = 1 ]; then
  python3 "$ROOT/tools/patch_scarletnx_zelda_shfl_predicate.py" "$SRC"
fi
if [ "${SCARLETNX_ZELDA_SHADER_WINDOW:-0}" = 1 ]; then
  python3 "$ROOT/tools/patch_scarletnx_zelda_shader_window.py" "$SRC"
fi
if [ "${SCARLETNX_ZELDA_CONDITIONAL_EXIT:-0}" = 1 ]; then
  python3 "$ROOT/tools/patch_scarletnx_zelda_conditional_exit.py" "$SRC"
fi
if [ "${SCARLETNX_ZELDA60_TOGGLE:-0}" = 1 ]; then
  python3 "$ROOT/tools/patch_scarletnx_zelda60_toggle.py" "$SRC" --mode runtime
  echo "Zelda Stable60: Home overlay toggle opt-in (ABI 12)"
fi
if [ "${SCARLETNX_RYUJINX_BRIDGE:-0}" = 1 ]; then
  python3 "$ROOT/tools/patch_scarletnx_ryujinx_runtime.py" "$SRC"
  echo "Castlevania: runtime Ryujinx privado e opt-in integrado ao Vulkan"
fi
if [ "${SCARLETNX_RYU_NATIVE_PROBE_BUILD:-0}" = 1 ]; then
  { [ "$BRANCH" = experimental/ryujinx-runtime-nativeaot ] ||
    [ "$BRANCH" = experimental/zelda-links-awakening-ryujinx-nativeaot ]; } ||
    { echo "NativeAOT LIVE probe requires its dedicated experimental branch" >&2; exit 1; }
  if [ "${SCARLETNX_RYU_V2:-0}" = 1 ]; then
    python3 "$ROOT/tools/patch_scarletnx_jit_cache.py" "$SRC"
    python3 "$ROOT/tools/ryujinx-nativeaot/patch_runtime_v2.py" "$SRC" \
      --identity "${SCARLETNX_RYU_V2_IDENTITY:?identidade ABI 2 obrigatoria}" \
      --revision "$(git rev-parse HEAD)"
  else
    python3 "$ROOT/tools/ryujinx-nativeaot/patch_scarletnx_live_probe.py" "$SRC"
  fi
  python3 "$ROOT/tools/ryujinx-nativeaot/patch_host1x_relocations.py" "$SRC"
  echo "NativeAOT: tradutor Ryujinx ao vivo; ABI 2=${SCARLETNX_RYU_V2:-0}"
fi
if [ "${SCARLETNX_ZELDA_PERF:-0}" = 1 ]; then
  python3 "$ROOT/tools/patch_scarletnx_zelda_perf.py" "$SRC" --revision "$(git rev-parse HEAD)"
  python3 "$ROOT/tools/patch_scarletnx_zelda_perf_opt.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_hash_span.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_transfer.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_uniform.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_clear_load.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_ub_extent.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_bind_reuse.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_shadow_capture.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_ww_diag.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_vb_pool.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_depth_range.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_lighting_diag.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_effect_depth.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_d24_pack.py" "$SRC"
  python3 "$ROOT/tools/patch_scarletnx_zelda_nx_compute.py" "$SRC"
fi
export SCARLETNX_CASTLEVANIA_FSWZADD=1
export SCARLETNX_RUNTIME_OUT="$OUT"
export SCARLETNX_PATCHED_RUNTIME_SO="$OUT"
echo "============================================="
echo "CASTLEVANIA: shader FSWZADD 0xD7 experimental"
echo "Mario runtime estavel: NAO sera sobrescrito"
echo "AOT 603 MB reutilizado; nao recompilar blocos"
echo "Diagnostico bindless ativo: op, pc, reg, def, producer, near, nearop, pred, srcA, srcB"
echo "============================================="
bash "$ROOT/compilar-mario-snx-romfs-termux.sh"
if [ ! -s "$OLD_APK" ]; then
  echo "ERRO: compilacao retornou sucesso mas APK nao foi encontrado: $OLD_APK" >&2
  exit 1
fi
echo "===== VERSAO EXPERIMENTAL GERADA ====="
echo "Runtime: $OUT"
echo "APK: /storage/emulated/0/Download/ZeldaRecomp/Zelda-SNX-Runtime-TESTE.apk"
