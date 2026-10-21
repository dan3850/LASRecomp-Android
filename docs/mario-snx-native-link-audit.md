# Mario ScarletNX: crash nativo antes de main

Escopo: branch `android/mario-snx-runtime-boot`, ScarletNX
`34853eeae5af132e320adbb0193f13344085bf89`, ABI 12. Esta correção não
regera o módulo AOT do Mario e mantém o graft de RomFS externa.

## Evidência e limites

O anexo `Mario-Recomp-boot (14).txt` registra a tentativa de 21/10/2026,
09:32:01 -03:00. O processo `:snx` termina em `getauxval`, chamado por
`init_have_lse_atomics`, durante `soinfo::call_constructors`/`dlopen`.
Os dois primeiros frames pertencem a `libscarletnx.so`, Build ID
`39c00e362c67389ce959bb2a1c3df78692d33ee0`. O launcher havia registrado
62.119.496 bytes para o runtime e 107.484.552 bytes para o AOT.
Essa tentativa não comprova entrada em `main()`.

O mesmo anexo contém logs históricos do jogo chegando à RomFS. Eles não
pertencem ao carregamento que caiu em `getauxval` e não validam esse build.

Foi possível inspecionar também o APK anterior enviado às 03:30. Seu runtime
tem 72.375.144 bytes, Build ID `4d1cbffdbafbf0c499ba99d6498872ca650cb52b`:
`getauxval` é importado como `UND`, versão `LIBC`, de `libc.so`. Esse ELF é
um controle de comparação; não é o ELF de 62 MB do tombstone atual.

O ELF atual, seus arquivos `.a` e o cache Ninja existem no celular e não
foram disponibilizados neste ambiente. Portanto, não se atribui sem prova
o objeto atual a um arquivo específico do NDK ou do Termux. O build abaixo
registra essa origem efetiva no próprio ambiente, antes de alterar o link.
Ausência dessa evidência antiga é registrada, nunca tratada como confirmação.

## Mecanismo investigado

O código original de ScarletNX não implementa `getauxval`. Seu
`src/common/cpu/recompiler/llvm/libc.inc` implementa operações de memória
para o objeto/bitcode dos módulos gerados, que são embutidos como dados no
runtime. Isso não justifica uma implementação host de `getauxval`.

No compiler-rt do LLVM 21.1.8, o construtor Android
`init_have_lse_atomics` consulta `getauxval(AT_HWCAP)`, testa
`HWCAP_ATOMICS` e mantém a correção para Exynos 9810. A correção não altera
esse algoritmo nem força uma resposta de capacidade da CPU.

Na Bionic, `getauxval` usa o vetor auxiliar de `__libc_shared_globals()`.
A inicialização da libc preenche esse vetor. Se objetos da libc estática
forem incorporados a um DSO e suas chamadas forem ligadas localmente,
o DSO pode ler sua própria cópia ainda nula desse estado. Carregar uma
biblioteca com `dlopen` não executa o startup de um executável estático.

O version script anterior não removia essa implementação. `local: *`
restringia exportações, preservando código e chamadas internas.
`-Bsymbolic` reforça a ligação local de definições já presentes. Removê-lo
genericamente também quebraria a premissa documentada pelo upstream para
as tabelas alcançadas pelo assembly do FFmpeg. Ele foi preservado.

Foi identificado nos scripts um risco concreto de seleção: um `-L` amplo
para o diretório geral do NDK precedia os diretórios de bibliotecas por API.
Também havia escolha independente de C++ no link, no APK original e no
staging LASRecomp. `-static-libstdc++` diz respeito ao runtime C++; sua
presença isolada não demonstra que a libc C foi ligada estaticamente.
O comando efetivo do driver e os membros extraídos são a evidência decisiva.

## Correção implementada

1. A busca usa primeiro o diretório Android API 26. O C++ é fornecido por
   caminho exato; não é necessário adicionar o diretório genérico do NDK
   à busca apenas para localizar esse arquivo.
2. O alvo `scarletnx` recebe explicitamente o import library oficial
   Android26 `libc.so`, antes dos archives, com `--no-as-needed` limitado
   por `--push-state`/`--pop-state`. Esse arquivo fornece a interface no
   link; a libc do Android fornece a implementação no processo. O stub
   do NDK não é empacotado no APK.
3. O C++ compartilhado do Termux usado com o LLVM é o mesmo arquivo no
   link e no pacote. SHA-256 vincula runtime/C++ ao manifesto local.
   O grafo SNX recebe o SONAME privado `libsnx_c++_shared.so`. Imports C++
   são conferidos contra esse provedor para detectar substituição por
   uma versão incompleta. Os símbolos C++ disponíveis são uma verificação
   de ligação, não uma prova completa de compatibilidade de ABI em execução.
4. A allowlist SDL/JNI permanece como delimitação de API. A condição para
   aceitar o runtime passou a ser a ausência de definições host privadas
   de libc, inclusive símbolos locais, e a presença de importação e
   relocation de `getauxval` versionada como `LIBC` de `libc.so`.
5. O construtor LSE original continua funcionando. Não foram adicionados
   wrappers `dlsym`, leitores alternativos de auxv, retornos constantes,
   exclusão do construtor, `-mno-outline-atomics` ou alteração de ABI 12.

Também foi corrigido um defeito independente do patch LLVM: cada nova
execução encontrava a consulta original dentro do `else` que ela mesma
gerara e aninhava outro bloco. Os blocos exatos antigos são normalizados
e a transformação agora é idempotente, sem regravar arquivos inalterados.

## Auditoria automática e origem dos objetos

`tools/scarletnx_elf_audit.py` usa apenas a biblioteca padrão do Python.
Examina `.dynsym` e `.symtab`, tipos/visibilidade, versões/import providers,
Build ID, `DT_NEEDED`, `DT_INIT`, `.init_array`, relocations e branches
diretos do construtor ARM64. Reconhece `STT_GNU_IFUNC`, `R_AARCH64_IRELATIVE`,
RELA/REL, Android APS2 e RELR. Não confunde endereço virtual com offset
de arquivo. As saídas completas de readelf/objdump são preservadas quando
essas ferramentas estão disponíveis.

O script de build cria uma pasta por tentativa em
`$HOME/.cache/lasrecomp-scarletnx-romfs/elf-audit/`:

| Arquivo | O que comprova |
| --- | --- |
| `before.json` | Símbolos, Build ID e estado do ELF existente antes do conserto |
| `before-ninja-commands.txt` | Comandos do grafo Ninja existente |
| `before-relink/command.json` | Link anterior e a mudança exclusiva de saída/diagnóstico |
| `before-relink/driver.txt` | Argumentos implícitos reais do compilador (`-###`) |
| `before-relink/link.log`, `before.map`, `before-why-extract.tsv` | Bibliotecas/objetos que forneceram os símbolos no link antigo |
| `before-relink/elf.json` | ELF da cópia de diagnóstico; comparação do código de `getauxval` com o original |
| `cxx-probe.json` | ELF do pequeno executável que consulta HWCAP na libc e é executado no Termux |
| `link.log`, `scarletnx.map`, `why-extract.tsv` | Origem efetiva dos símbolos no link corrigido |
| `after.json` | Auditoria do runtime corrigido e trechos de proveniência do link |
| `*-archive-*.txt` | Índices de símbolos dos archives examinados; fornecedores candidatos, não prova de extração |
| `selected-runtime-libraries.json` | Caminhos e hashes das bibliotecas selecionadas |

Os índices de archives são diagnósticos auxiliares. Um `llvm-nm` com erro
não interrompe a compilação nem elimina o relatório ELF: seu código de
saída, stdout e stderr são preservados em `*-archive-*.txt` e descritos
em `archive_diagnostics`. Símbolos de uma saída parcial ficam explicitamente
em `partial_providers`, fora de `archive_providers`. O console registra
`ELF_AUDIT_DIAGNOSTIC_WARNING`; falhas auxiliares de readelf/objdump recebem
o mesmo tratamento. A auditoria direta do ELF e as verificações de C++
continuam obrigatórias e rejeitam o runtime incompatível.

Na execução de 21/10/2026 às 10:14, o coletor anterior parou em
`$PREFIX/lib/libatomic.a` porque tratava o retorno não zero de `llvm-nm`
como fatal, antes de salvar o stderr. Esse log não estabelece a causa
do erro da ferramenta nem o formato desse arquivo no celular. A regressão
usa um linker script chamado `.a` para reproduzir um retorno não zero real,
sem atribuir esse formato ao arquivo do usuário.

O replay antigo só acontece se o ELF contém definições de libc suspeitas.
Ele é um relink de diagnóstico em outro arquivo, necessário para atribuir
os símbolos aos objetos efetivos: não compila fontes, altera archives ou
substitui o runtime. Se objetos antigos não estiverem disponíveis, guarda
o limite e prossegue para a correção; a auditoria do ELF corrigido continua
obrigatória. O caminho da tentativa mais recente fica em
`$HOME/.cache/lasrecomp-scarletnx-romfs/latest-elf-audit.path`.

O empacotador repete a auditoria na entrada, depois de `patchelf` e no
membro do APK assinado. Também compara o SHA-256 do AOT empacotado com
o original do usuário. Um AOT alterado ou um runtime com libc interna
interrompe a entrega. Logs de staging ficam em
`$HOME/.cache/lasrecomp-mario-snx/`.

Nenhum cache CMake/Ninja/Gradle/LLVM/FFmpeg/OpenSSL/SDL é limpo. A alteração
de opções provoca relink, e o marcador em `entry.c` recompila esse objeto.
Os demais passos seguem as dependências incrementais existentes.

## Validação feita fora do celular

- 17 testes em `tests/test_scarletnx_android_link.py`, usando ELFs ARM64
  reais compilados com Clang/LLD (via Zig no ambiente de validação).
- Caso negativo com `getauxval` local, invisível na tabela dinâmica;
  também caso stripped, IFUNC e archive `libc.a` sombreando o import.
- Caso corrigido com import `LIBC`, `JUMP_SLOT` e construtor resolvido,
  inclusive APS2, RELR e `android+relr`.
- Falhas de nm, incluindo saída parcial e executável ausente, preservam
  os diagnósticos; um ELF incorreto continua rejeitado em modo obrigatório.
  Falhas dos dumps auxiliares também preservam o relatório principal.
- Regressão nativa em subprocesso Linux: cópia privada nula provoca
  SIGSEGV durante o carregamento; import da libc do processo carrega.
  Esse teste demonstra o mecanismo, não executa a Bionic/Android.
- 2 testes de layout ABI 12 já existentes.
- Sintaxe Bash completa dos dois scripts; AST/compilação dos Python
  alterados e de todos os heredocs Python embutidos.
- Aplicação duas vezes sobre os arquivos reais do commit ScarletNX
  fixado, incluindo o patch de RomFS: uma única alteração, sem duplicação.

A CI `ScarletNX native linkage regressions` executa os testes pequenos
sem ROM, AOT do Mario ou recompilação integral do runtime.

## Teste real e critério de sucesso

O launcher limpa `mario-snx-native.log` antes de cada tentativa e configura
`SNX_BOOT_TRACE` depois do carregamento nativo. O primeiro trecho do
verdadeiro `main()` de ScarletNX grava `SCARLETNX_MAIN_ENTERED` nesse
arquivo e no logcat. O arquivo é incluído por **Salvar log**.

O marcador comprova a entrada no runtime host. Depois dele, problemas de
RomFS, CPU/Horizon, Vulkan ou inicialização do jogo devem ser examinados
pelos logs dessa tentativa. A validação inicial fora do celular não
comprovava boot ou jogabilidade do Mario. O relato posterior do usuário
está registrado abaixo.

## Tela cheia após o boot

Em 21/10/2026 o usuário relatou o jogo rodando e enviou uma captura com
Mario renderizado, mas com a barra de título do ScarletNX, a barra de
status e os botões de navegação Android ainda ocupando a tela. Essa captura
comprova um avanço além do carregamento nativo; não mede estabilidade,
velocidade do jogo nem identifica o Build ID do runtime instalado.

O launcher não definia um tema sem título para `MarioSnxGameActivity` e
não passava `--fullscreen`. No ScarletNX fixado, `settings.txt` define
`fullscreen=0` por padrão e `backend/sdl3.c` só solicita fullscreen quando
essa opção está ativa. O próprio SDL 3.4.18 começa com
`setWindowStyle(false)` e escreve o título nativo no título da Activity.

O tema da Activity agora é `Theme.Material.NoActionBar.Fullscreen` e o
launcher passa `--fullscreen`, reconhecido pelo CLI desse commit. A Activity
esconde as barras com `WindowInsetsController` no Android 11 ou posterior,
com reaplicação ao retomar e recuperar foco. O gesto da borda revela as
barras temporariamente. Android 8–10 usa os flags imersivos correspondentes.
Os metadados SDL mantêm as duas orientações paisagem, inclusive quando a
janela nativa solicita ser redimensionável.

Essa mudança é Java/manifesto: basta executar
`bash compilar-mario-snx-runtime-termux.sh` no worktree existente, sem
executar o build de RomFS/ScarletNX. O empacotador reutiliza o runtime,
o provedor C++ registrado e o AOT existentes e mantém a auditoria do APK.
A imagem permanece na proporção original; telas mais largas podem manter
faixas laterais. A disposição dos controles e o overlay de desempenho do
RedMagic não são alterados por essa correção da janela.

Validação: manifesto XML, sintaxe Java e Bash, 17 regressões de ligação/
sintaxe e 2 testes ABI 12. A apresentação visual e o retorno de Home/
notificações com as barras novamente ocultas precisam do teste no celular.

## Comandos únicos para Termux

Execute no worktree existente `LASRecomp-Mario-Teste`, que já usa a branch
solicitada. A atualização é fast-forward; alterações locais rastreadas
fazem o bloco parar sem descartá-las. Não é necessário trocar de branch
no outro checkout `LASRecomp-Android`.

```bash
(
set -euo pipefail
cd "$HOME/LASRecomp-Mario-Teste"
BRANCH="android/mario-snx-runtime-boot"
test "$(git branch --show-current)" = "$BRANCH"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  git status --short
  echo "ERRO: preserve suas alteracoes locais antes de atualizar."
  exit 1
fi
LOG_DIR="/storage/emulated/0/Download/MarioRecomp/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/mario-snx-link-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
trap 'echo "Log desta execucao: $LOG"' EXIT
git fetch origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"
export SCARLETNX_BUILD_JOBS=2
export LASRECOMP_JOBS=2
python3 tests/test_scarletnx_android_link.py
python3 tests/test_mario_snx_probe.py
bash compilar-mario-snx-romfs-termux.sh
echo "APK: /storage/emulated/0/Download/MarioRecomp/Mario-SNX-Runtime-BOOT.apk"
echo "Auditoria: $(cat "$HOME/.cache/lasrecomp-scarletnx-romfs/latest-elf-audit.path")"
)
```

Instale o APK, use **INICIAR MARIO — CPU ScarletNX** e depois **Salvar log**.
O resultado esperado para este defeito é `SCARLETNX_MAIN_ENTERED` na
tentativa atual, acompanhado da ausência do antigo SIGSEGV em `getauxval`.

## Fontes primárias consultadas

- [ScarletNX: CMake Android e -Bsymbolic](https://github.com/scarletnx/ScarletNX/blob/34853eeae5af132e320adbb0193f13344085bf89/src/nx/CMakeLists.txt)
- [ScarletNX: entrada real](https://github.com/scarletnx/ScarletNX/blob/34853eeae5af132e320adbb0193f13344085bf89/src/nx/runtime/entry.c)
- [ScarletNX: libc dos módulos gerados](https://github.com/scarletnx/ScarletNX/blob/34853eeae5af132e320adbb0193f13344085bf89/src/common/cpu/recompiler/llvm/libc.inc)
- [LLVM 21.1.8: construtor LSE Android](https://github.com/llvm/llvm-project/blob/llvmorg-21.1.8/compiler-rt/lib/builtins/cpu_model/aarch64/lse_atomics/android.inc)
- [Bionic Android 16: getauxval](https://github.com/aosp-mirror/platform_bionic/blob/android-16.0.0_r1/libc/bionic/getauxval.cpp)
- [Bionic: startup estático e shared globals](https://android.googlesource.com/platform/bionic/+/master/libc/bionic/libc_init_static.cpp)
- [Bionic Android 16: relocations APS2](https://github.com/aosp-mirror/platform_bionic/blob/android-16.0.0_r1/linker/linker_reloc_iterators.h)
- [NDK: precedência dos diretórios por API e import libraries](https://android.googlesource.com/platform/ndk/+/master/docs/BuildSystemMaintainers.md)
- [SDL 3.4.18: Activity e comandos de janela](https://github.com/libsdl-org/SDL/blob/release-3.4.18/android-project/app/src/main/java/org/libsdl/app/SDLActivity.java)
- [Android: modo imersivo e barras transitórias](https://developer.android.com/develop/ui/views/layout/immersive)
