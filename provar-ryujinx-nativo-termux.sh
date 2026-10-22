#!/data/data/com.termux/files/usr/bin/bash
# Prova independente do tradutor REAL Ryujinx como biblioteca Android ARM64.
# NAO usa pack .snxrbr, NAO altera APK/AOT/ScarletNX/cache grafico.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
BRANCH="experimental/ryujinx-runtime-nativeaot"
if [ "$(git branch --show-current)" != "$BRANCH" ]; then
  echo "ERRO: rode somente na branch $BRANCH" >&2
  exit 1
fi

NX="$HOME/.cache/lasrecomp-ryujinx-probe/nxnative"
SRC="$ROOT/tools/ryujinx-nativeaot"
WORK="$HOME/.cache/lasrecomp-ryujinx-nativeaot"
STAGED="$WORK/source"
PUBLISH="$WORK/publish"
RESULT="$HOME/ryujinx-nativeaot"
mkdir -p "$RESULT" "$STAGED" "$PUBLISH"

if [ ! -f "$NX/dm/gfx/tools/dmsh_xlate/Program.cs" ] ||
   [ ! -f "$NX/dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Ryujinx.Graphics.Shader.csproj" ]; then
  echo "ERRO: o tradutor Ryujinx completo nao esta no cache do Termux:" >&2
  echo "  $NX" >&2
  echo "Ele e obtido pelo script ja existente rodar-castlevania-ryujinx-termux.sh." >&2
  echo "NAO execute outro build por enquanto; primeiro confirme esse checkout." >&2
  exit 1
fi
if ! command -v dotnet >/dev/null 2>&1 ||
   ! command -v clang >/dev/null 2>&1 ||
   ! command -v python3 >/dev/null 2>&1; then
  echo "ERRO: requer dotnet SDK 10, clang e python3 no Termux." >&2
  exit 1
fi

set -- /storage/emulated/0/Download/Castlevania-shaders-SNXS*.zip
if [ ! -s "$1" ]; then
  echo "ERRO: precisa do ZIP dos shaders ORIGINAIS em Download para testar." >&2
  exit 1
fi
{
  echo "===== PROVA: TRADUTOR NATIVO REAL, SEM SHADER PREGERADO ====="
  echo "Branch: $BRANCH"
  echo "dotnet $(dotnet --version)"
  python3 "$SRC/prepare_source.py" --nxnative "$NX" --out "$STAGED"
  echo "===== NativeAOT: linux-bionic-arm64 (cache .NET reaproveitado) ====="
  dotnet publish "$STAGED/RyujinxShaderNative.csproj" \
    -c Release -r linux-bionic-arm64 \
    -p:RyuSrc="$NX/dm/third_party/ryujinx" \
    -p:PublishAot=true -p:NativeLib=Shared \
    -p:DisableUnsupportedError=true -p:PublishAotUsingRuntimePack=true \
    -p:StripSymbols=false --nologo -o "$PUBLISH"
  SO="$PUBLISH/libRyujinxShaderNative.so"
  if [ ! -s "$SO" ]; then
    echo "ERRO: a compilacao NAO gerou a biblioteca nativa esperada em: $SO" >&2
    exit 1
  fi
  echo "===== LIB NATIVA ENCONTRADA ====="
  ls -lh "$SO"
  echo "===== TESTANDO SHADERS POR C ABI, SEM PACKS PRIVADOS ====="
  python3 "$SRC/test_native.py" "$SO" "$@" --out "$RESULT/shaders"
  echo "===== CONCLUIDO ====="
  echo "Biblioteca de teste: $SO"
  echo "Shaders de teste: $RESULT/shaders"
  echo "O aplicativo nao foi modificado; esta e a prova antes de ligar no Vulkan."
} 2>&1 | tee "$RESULT/build.log"
