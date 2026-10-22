#!/data/data/com.termux/files/usr/bin/bash
# Testa a biblioteca C# Ryujinx compilada como NativeAOT Android ARM64.
# NAO altera APK, AOT do jogo, shader cache ou ScarlettNX.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
BRANCH="experimental/ryujinx-runtime-nativeaot"
if [ "$(git branch --show-current)" != "$BRANCH" ]; then
  echo "ERRO: rode na branch $BRANCH" >&2
  exit 1
fi

OUT="$HOME/ryujinx-nativeaot"
SO="$OUT/libRyujinxShaderNative.so"
mkdir -p "$OUT/shaders"

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
  for candidate in /storage/emulated/0/Download/ryujinx-android-arm64-nativeaot*.zip; do
    if [ -s "$candidate" ] && { [ -z "$ARCHIVE" ] || [ "$candidate" -nt "$ARCHIVE" ]; }; then
      ARCHIVE="$candidate"
    fi
  done
fi
if [ -z "$ARCHIVE" ] || [ ! -s "$ARCHIVE" ]; then
  echo "O artefato da biblioteca ainda nao esta na pasta Download." >&2
  echo "Acesse o build Android ARM64 em:" >&2
  echo "https://github.com/dan3850/LASRecomp-Android/actions/workflows/ryujinx-nativeaot-android.yml" >&2
  echo "Baixe o artefato ryujinx-android-arm64-nativeaot.zip para Download." >&2
  echo "Quando estiver la, execute este mesmo script. Nao precisa compilar APK." >&2
  exit 2
fi

CAPTURES=()
for file in /storage/emulated/0/Download/Castlevania-shaders-SNXS*.zip; do
  if [ -s "$file" ]; then CAPTURES+=("$file"); fi
done
if [ "${#CAPTURES[@]}" -eq 0 ]; then
  echo "ERRO: nao foi localizado o ZIP original Castlevania-shaders-SNXS.zip." >&2
  exit 1
fi

echo "===== BIBLIOTECA RYUJINX NATIVA ARM64 ====="
echo "Arquivo: $ARCHIVE"
python3 "$ROOT/tools/ryujinx-nativeaot/extract_artifact.py" "$ARCHIVE" --out "$SO"
echo "===== TESTANDO RYUJINX C# REAL VIA ABI NATIVA ====="
echo "Quantidade de ZIPs de captura: ${#CAPTURES[@]}"
python3 "$ROOT/tools/ryujinx-nativeaot/test_native.py" \
  "$SO" "${CAPTURES[@]}" --out "$OUT/shaders" 2>&1 | tee "$OUT/test.log"
echo "===== CONCLUIDO ====="
echo "Log: $OUT/test.log"
echo "Este teste nao altera a APK ou o jogo; so comprova o tradutor no Android."
