#!/data/data/com.termux/files/usr/bin/bash
# Prepare the clean ScarletNX Zelda runtime source, without building or changing stable caches.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCARLETNX_UPGRADE_SOURCE:-$HOME/.cache/lasrecomp-scarletnx-upgrade/ScarletNX}"
TARGET=05324b57629d0894506b31beb2c72869138b7ad1
cd "$ROOT"
[ "$(git branch --show-current)" = android/scarletnx-full-upgrade ] || {
  echo "ERRO: selecione android/scarletnx-full-upgrade"; exit 1;
}
if [ -d "$SRC/.git" ]; then
  [ "$(git -C "$SRC" rev-parse HEAD)" = "$TARGET" ] || { echo "ERRO: revisao inesperada"; exit 1; }
  STATUS="$(git -C "$SRC" status --porcelain)"
  if [ -n "$STATUS" ]; then
    case "$STATUS" in
      " M src/nx/hle/filesystem/fs.c"|" M cmake/llvm.cmake"|" M cmake/llvm.cmake"
    grep -q 'SNX_EXTERNAL_ROMFS' "$SRC/src/nx/hle/filesystem/fs.c" || { echo "ERRO: fs.c modificado sem RomFS"; exit 1; }
  fi
else
  bash "$ROOT/preparar-scarletnx-completo-termux.sh"
fi
python3 "$ROOT/tools/auditar_scarletnx_novo.py" "$SRC"
python3 "$ROOT/tools/auditar_build_scarletnx_2026.py" "$SRC" || {
  echo "AVISO: existem incompatibilidades de compilacao a adaptar; nao compilando APK.";
}
python3 "$ROOT/tools/patch_scarletnx_llvm_2026.py" "$SRC" --check
python3 "$ROOT/tools/patch_scarletnx_romfs_2026.py" "$SRC" --check
python3 "$ROOT/tools/patch_scarletnx_romfs_2026.py" "$SRC"
python3 "$ROOT/tools/patch_scarletnx_llvm_2026.py" "$SRC"
grep -q 'SNX_EXTERNAL_ROMFS' "$SRC/src/nx/hle/filesystem/fs.c" || {
  echo "ERRO: graft RomFS nao aplicado"; exit 1;
}
echo "PREPARACAO_OK: ScarletNX novo com apenas RomFS Android; D24, Stable60 e graficos antigos nao aplicados."
echo "FONTE: $SRC"
echo "Nenhum runtime ou APK foi compilado. A integracao do linker Android ainda e necessaria."
\n'" M src/nx/hle/filesystem/fs.c") ;;
      *) echo "ERRO: alteracoes nao reconhecidas: $STATUS"; exit 1 ;;
    esac
    grep -q 'SNX_EXTERNAL_ROMFS' "$SRC/src/nx/hle/filesystem/fs.c" || { echo "ERRO: fs.c modificado sem RomFS"; exit 1; }
  fi
else
  bash "$ROOT/preparar-scarletnx-completo-termux.sh"
fi
python3 "$ROOT/tools/auditar_scarletnx_novo.py" "$SRC"
python3 "$ROOT/tools/auditar_build_scarletnx_2026.py" "$SRC" || {
  echo "AVISO: existem incompatibilidades de compilacao a adaptar; nao compilando APK.";
}
python3 "$ROOT/tools/patch_scarletnx_romfs_2026.py" "$SRC" --check
python3 "$ROOT/tools/patch_scarletnx_romfs_2026.py" "$SRC"
grep -q 'SNX_EXTERNAL_ROMFS' "$SRC/src/nx/hle/filesystem/fs.c" || {
  echo "ERRO: graft RomFS nao aplicado"; exit 1;
}
echo "PREPARACAO_OK: ScarletNX novo com apenas RomFS Android; D24, Stable60 e graficos antigos nao aplicados."
echo "FONTE: $SRC"
echo "Nenhum runtime ou APK foi compilado. A integracao do linker Android ainda e necessaria."
