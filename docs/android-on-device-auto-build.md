# LASRecomp Android — preparação automática local (branch experimental)

**Objetivo:** um único APK público, sem arquivos Nintendo, em que o usuário
seleciona uma pasta previamente extraída do próprio Link's Awakening v1.0.0.
O aplicativo prepara o jogo no dispositivo e mantém o código gerado no armazenamento
privado, sem publicar nada ou exigir Termux no produto final.

## Diagnóstico do código atual

- **Já implementado:** `GameImportActivity` seleciona a pasta usando o Android
  Storage Access Framework, importa `exefs/main`, `exefs/sdk`,
  `exefs/main.npdm` e `romfs/`, valida o identificador v1.0.0 e cria
  `romfs.bin` com `nativePrepareGame`. Há tela de status e botão Jogar
  protegido por checagem das bibliotecas instaladas.
- **Disponível somente fora do APK:** `tools/gen.py` (Python + Unicorn/Capstone/LZ4)
  gera fontes C, e `tools/compile-generated-android-termux.sh` compila
  a biblioteca usando o Clang do **Termux**. O resultado é **derivado do jogo**:
  nunca publicá-lo.
- **Bloqueio atual:** `runtime/platform/android.c` não implementa spawn de
  compiladores no APK e `runtime/gamelib.c` procura `liblasgame.so`
  apenas entre as bibliotecas instaladas junto do APK. Não existe ainda
  recompilador offline integrado ao aplicativo.

## Etapas, em ordem

1. **Viabilidade do carregador (implementação experimental nesta branch):**
   botão de diagnóstico na tela de importação. Carrega apenas uma biblioteca
   de teste inofensiva, originalmente incluída no próprio APK; o código JNI
   copia-a para o cache privado, torna a cópia somente leitura, tenta
   `dlopen`/`dlsym`, verifica um valor de retorno e apaga a cópia.
   O teste **não** cria nem usa código Zelda.
2. **Validar no Android real:** registrar no RedMagic o resultado do diagnóstico,
   o nível de API/target SDK e o erro do linker, se houver. Um OK nesse teste
   NÃO prova que a biblioteca grande funciona (dependências HLE, relocations,
   SELinux, namespaces e RAM precisam de testes adicionais).
3. **Carregamento nativo privado:** somente se a política Android permitir,
   criar um carregador com validação de ABI, identidade do gerador e origem da
   biblioteca, gravação atômica e arquivo não gravável antes de `dlopen`.
   Nunca carregar arquivos externos arbitrários. Se falhar, pesquisar outro
   modelo tecnicamente compatível; não desabilitar segurança Android.
4. **Gerador embutido:** portar ou empacotar o gerador AArch64/NSO para Android
   com todas as suas dependências, sem pressupor Python do Termux nem Ubuntu.
5. **Compilador embutido:** integrar backend AArch64/Android/Bionic capaz de
   produzir um `liblasgame.so` compatível a partir do C gerado, com limite
   de memória, armazenamento e progresso. Preferir jobs pequenos, temporários
   e reaproveitamento de objetos concluídos.
6. **Coordenador de preparação:** confirmar versão e espaço livre, gerar SDK
   e main, compilar, validar a ELF ARM64/ABI/símbolos/dependências, instalar
   no cache privado, guardar o hash dos executáveis e versão das ferramentas.
   Após uma preparação bem-sucedida, o botão Jogar reutiliza a biblioteca.
   Falhas devem preservar dados válidos e oferecer logs sem conteúdo do jogo.

## Teste atual

- Use o APK compilado **desta branch**, não o APK antigo do GitHub Actions.
- Abra o aplicativo e toque em **DIAGNÓSTICO: TESTAR BIBLIOTECA LOCAL**.
- Resultado `OK`: o Android carregou a biblioteca inofensiva copiada para o
  cache somente leitura, **não** significa que Zelda já executa.
- Resultado `FALHOU`: copiar a mensagem completa para identificar a restrição
  do linker. A cópia de teste é excluída após a tentativa.
- A `liblasgame.so` que está sendo gerada separadamente no Termux continua
  útil para validar o motor, mas **não será enviada ao GitHub**.

**Não concluído nesta branch:** recompilação automática real, biblioteca do
jogo instalada sem APK privado, boot do Zelda, desempenho e segurança em
aparelhos diferentes. O APK público continua sem código ou recursos Nintendo.
