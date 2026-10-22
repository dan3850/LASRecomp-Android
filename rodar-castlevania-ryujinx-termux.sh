#!/data/data/com.termux/files/usr/bin/bash
# Offline Maxwell shader comparison with nxnative's vendored Ryujinx translator.
# This never rebuilds Castlevania AOT, overwrites an APK, or edits ScarletNX.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [ "$(git branch --show-current)" != "experimental/castlevania-belmonts-curse" ]; then
  echo "ERRO: use experimental/castlevania-belmonts-curse" >&2
  exit 1
fi
ZIP="${1:-}"
if [ -z "$ZIP" ]; then
  for file in /storage/emulated/0/Download/Castlevania-shaders-SNXS*.zip; do
    if [ -s "$file" ] && { [ -z "$ZIP" ] || [ "$file" -nt "$ZIP" ]; }; then ZIP="$file"; fi
  done
fi
if [ ! -s "$ZIP" ]; then
  echo "ERRO: ZIP SNXS nao encontrado em Downloads." >&2
  echo "Exporte shaders no APK e opcionalmente informe o ZIP como argumento." >&2
  exit 1
fi
OUT="$HOME/castlevania-ryujinx-probe"
NX="$HOME/.cache/lasrecomp-ryujinx-probe/nxnative"
mkdir -p "$OUT"
python3 -m unittest discover -s tests -p 'test_castlevania_ryujinx_probe.py'
if ! command -v dotnet >/dev/null 2>&1; then
  if ! command -v pkg >/dev/null 2>&1; then
    echo "ERRO: dotnet SDK 10 ausente e 'pkg' do Termux indisponivel." >&2
    exit 1
  fi
  echo "Instalando .NET SDK 10 do Termux (sem compilar o jogo)..."
  pkg install -y dotnet-sdk-10.0
fi
echo "===== DOTNET ====="
dotnet --version
if [ ! -d "$NX/.git" ]; then
  if [ -e "$NX" ]; then echo "ERRO: $NX existe, mas nao e checkout Git." >&2; exit 1; fi
  mkdir -p "$(dirname "$NX")"
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/seedds/nxnative "$NX"
fi
git -C "$NX" sparse-checkout set \
  dm/gfx/tools/dmsh_xlate dm/third_party/ryujinx
if [ ! -f "$NX/dm/gfx/tools/dmsh_xlate/dmsh_xlate.csproj" ]; then
  echo "ERRO: ferramenta Ryujinx indisponivel no checkout nxnative." >&2
  exit 1
fi
echo "===== RYUJINX - PROVA ISOLADA ====="
echo "ZIP: $ZIP"
echo "nxnative: $(git -C "$NX" rev-parse --short HEAD)"
echo "Saida: $OUT"
python3 "$ROOT/tools/castlevania_ryujinx_probe.py" \
  "$ZIP" --out "$OUT" --nxnative "$NX" \
  2>&1 | tee "$OUT/ryujinx-run.log"
echo "===== CONCLUIDO ====="
echo "Leia: $OUT/ryujinx-run.log e $OUT/report.json"
echo "NENHUM APK OU AOT FOI MODIFICADO."
