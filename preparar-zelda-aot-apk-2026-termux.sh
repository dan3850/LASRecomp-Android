#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="${HOME}/.cache/lasrecomp-scarletnx-upgrade"
TITLE="01006BB00C6F0000"
GAME="${ROOT}/zelda-aot-2026/${TITLE}"
STAGE="${ROOT}/zelda-apk-staging-2026"
RUNTIME="${GAME}/${TITLE}"
CODE="${GAME}/${TITLE}_code.so"
for file in "$RUNTIME" "$CODE" "${GAME}/${TITLE}.abi" "${GAME}/${TITLE}.ini"; do
  if [[ ! -s "$file" ]]; then echo "ERRO: arquivo AOT ausente: $file" >&2; exit 1; fi
done
command -v readelf >/dev/null || { echo "Instale binutils no Termux"; exit 1; }
command -v file >/dev/null || { echo "Instale file no Termux"; exit 1; }
echo "=== VERIFICANDO ARQUITETURA ==="
for file in "$RUNTIME" "$CODE"; do
  file "$file"
  readelf -h "$file" | grep -E 'Class:|Machine:|Type:'
  readelf -h "$file" | grep -q 'AArch64' || { echo "ERRO: biblioteca nao ARM64: $file" >&2; exit 1; }
done
echo "=== DEPENDENCIAS DO RUNTIME ==="
readelf -d "$RUNTIME" | grep NEEDED || true
echo "=== DEPENDENCIAS DO CODIGO AOT ==="
readelf -d "$CODE" | grep NEEDED || true
echo "=== BUSCANDO LLVM E C++ DO ANDROID ==="
for name in libLLVM.so libc++_shared.so; do
  found=""
  for candidate in "${ROOT}/output/${name}" "${PREFIX}/lib/${name}" "${ROOT}/termux-aot-cli-2026/${name}"; do
    if [[ -s "$candidate" ]]; then found="$candidate"; break; fi
  done
  if [[ -n "$found" ]]; then
    echo "$name: $found"
    file "$found"
  else
    echo "ATENCAO: $name nao encontrado nos caminhos conhecidos"
  fi
done
echo "=== CRIANDO STAGING PRIVADO (SEM APK) ==="
mkdir -p "$STAGE/game"
cp -f "$RUNTIME" "$CODE" "${GAME}/${TITLE}.abi" "${GAME}/${TITLE}.ini" "$STAGE/game/"
cp -a "${GAME}/${TITLE}_data" "$STAGE/game/"
cat > "$STAGE/README.txt" <<EOF
Pacote privado de staging para integrar ao APK Android experimental.
Title ID: $TITLE
Runtime: game/$TITLE
Codigo AOT: game/${TITLE}_code.so
Dados: game/${TITLE}_data
AVISO: o runtime foi copiado de libscarletnx.so; nao foi validado como entrada JNI nem como executavel standalone.
AVISO: os arquivos do jogo e o codigo recompilado nao devem ser publicados.
AVISO: isto nao e um APK; ainda faltam carregador Android, resolucao de bibliotecas e teste de inicializacao.
EOF
echo "=== STAGING CONCLUIDO ==="
du -sh "$STAGE"
echo "STAGING_READY=$STAGE"
