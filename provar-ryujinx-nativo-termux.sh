#!/data/data/com.termux/files/usr/bin/bash
# Retrocompatibilidade: a compilacao NativeAOT Android precisa de um host Linux.
# O .NET Termux nao distribui runtime.linux-bionic-arm64.Microsoft.DotNet.ILCompiler.
# O GitHub Actions produz a biblioteca real Ryujinx e este comando a TESTA.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "A compilacao Ryujinx NativeAOT agora e feita pelo GitHub Actions."
echo "O Termux apenas carrega e testa a biblioteca Android no aparelho."
echo "O APK, AOT e cache Vulkan permanecem intactos."
exec bash "$ROOT/testar-ryujinx-nativo-termux.sh" "$@"
