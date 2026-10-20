# Auditoria do boot do Mario e correção de timeout

Branch: `android/mario-full-recompiler-test`.
Base auditada: `107c83cf02428fc73eca2a88299ca9fa8651ae22`.

## Resultado e limite da conclusão

Foi corrigida uma violação reproduzível do contrato de
`WaitProcessWideKeyAtomic`, em `runtime/kernel.c`, função
`svc_wait_process_wide_key`. A correção elimina uma aquisição duplicada do
mutex e uma espera potencialmente infinita depois de um timeout.

**A causa da tela preta específica ainda não foi demonstrada. Não há teste
do jogo no aparelho com esta correção.** As primeiras esperas registradas
no log usam timeout infinito; esse registro não demonstra a passagem pelo
caminho de timeout corrigido. Uma correção de kernel com testes sintéticos
não equivale à confirmação de uma cena renderizada.

Não foram alterados os geradores, as entradas internas já reparadas, o timing,
os contadores GPU, o áudio, os serviços Horizon ou a apresentação Vulkan.
Não foi adicionada instrumentação ao runtime nesta alteração.

## Evidência utilizada

- Histórico e fontes da branch na base acima.
- `Mario-Recomp-boot(20261020-040330).txt`, exportado pelo usuário, com as
  seções independentes de gráficos e esperas e o log de execução.
- `mario-salto-grafico.txt`, `mario-diagnostico-tela-preta.txt` e a relação
  de recursos anteriormente fornecida, para conferir as observações históricas.
- Inspeção privada do APK antigo fornecido pelo usuário, identificado pelo
  próprio `SOURCE_VERSION.txt` como `bdfdaf9`. Esse APK não representa o HEAD
  atual. Seu perfil registra o SDK Build ID
  `204eaef83fe5e5617d0787c8ef01a080000bcd9a` e a identidade de biblioteca
  também vista nos logs posteriores. Não foi usado como prova do estado das
  reentradas reparadas depois dele.

Nenhum APK, recurso, biblioteca do jogo ou código recompilado foi adicionado
ao repositório.

## Fluxo auditado

| Etapa | Implementação e conclusão sustentada |
| --- | --- |
| Entrada Android | `runtime/main.c`: `lasrecomp_android_start` reserva a memória guest; `boot` carrega biblioteca, NSOs e identidade antes de criar a thread. O log confirma que essa etapa terminou. |
| Identidade e relocação | `runtime/gamelib.c`, `runtime/loader.c`, `tools/mario_boot_profile.py`: bases registradas e Build IDs, em vez de offsets presumidos do Zelda. Os testes exercitam rejeição de NSO incompatível e serviço HLE ausente. |
| Bootstrap SDK | `runtime/mario_startup.c`: escolhe o export real de `nn::init::Start`, prepara os callbacks e inicia a thread. O log registra a variante de cinco argumentos em `sdk+0x2a3700`, seguida de inicialização de SDK e main. |
| Construtores | `initialize_modules` executa dependências antes do main; `DT_INIT` tem precedência sobre o array. Os testes verificam as variantes de quatro/cinco argumentos e arrays por efeitos na memória guest. Isso não valida todos os construtores do executável comercial. |
| Despacho e recompilação | `runtime/dispatch.c`, `tools/gen.py`, `tools/lifter.py`, `tools/mario_full_recompile.py` e reparo de reentradas: chamadas, memória, SIMD e retorno/reentrada são exercitados com NSOs sintéticos e referência ARM64. Não existe, nestes logs, um trap atual que identifique outra entrada ausente. Isso não prova cobertura de todos os caminhos do jogo. |
| Recursos e threads | O log confirma RomFS por SAF, índice com 3.778 arquivos, leituras e criação de threads. Após o terceiro present ainda aparecem consultas de recursos da cena e `LayoutData/RCS_TopMenu`. O observador as identifica pelo retorno `main+0x8a1a5c`; não é um rastreamento completo da thread principal. |
| Gráficos | `nvnQueueSubmitCommands` executa listas; `nvnQueuePresentTexture` chega a `backend_present`. Há aquisição bem-sucedida e `VK_SUBOPTIMAL_KHR` nos presents registrados. O resultado não demonstra uma falha fatal de apresentação. |
| Primeira cena | Não comprovada. Falta uma amostra do ponto de execução das threads no estado preto, depois que os registros limitados deixaram de mostrar atividade. |

## O que o contador de desenhos mede

`mario_guest_draw_count` devolve `cum_draws`, em
`runtime/nvn/vulkan/exec.c`. O incremento está no final de `draw`, depois
de `vkCmdDraw`/`vkCmdDrawIndexed`. Contabiliza um desenho guest aceito por
essa função; uma divisão em vários runs não aumenta esse contador por run.

Ele não conta `CMD_CLEAR_COLOR`, limpezas por desenho auxiliar, o triângulo
de apresentação nem a UI. Também não conta desenhos recusados antes desse
ponto, por exemplo por falta de programa/pipeline.

Há lacunas anteriores à contagem: `DrawArraysIndirect` e
`DrawElementsIndirect` são gravados por `cmdbuf.c`, mas não têm tratamento
no switch de `exec_list`; `MultiDraw*IndirectCount` e `DrawTexture` possuem
corpos vazios no gravador. **Não há evidência de que o Mario os tenha usado
nesse ponto**, portanto não foram implementados por suposição.

Os eventos de present imprimem os três primeiros e depois amostras
periódicas; os totais de desenhos são amostrados a cada 60 frames. A ausência
de um quarto evento não prova, sozinha, que o contador final seja exatamente
três. Prova pelo menos os três frames e os três desenhos registrados.

## Defeito corrigido

Antes, `svc_wait_process_wide_key` fazia:

1. Liberava o mutex e esperava a condição.
2. Se a espera retornasse erro/timeout, adquiria o mutex novamente, até com
   `block_current(-1)` se outro proprietário o mantivesse.
3. Só então devolvia o timeout ao SDK.

Isso viola o contrato da chamada: após timeout, a aquisição é responsabilidade
do código do SDK. O runtime podia entregar o mutex já adquirido para uma
segunda aquisição ou continuar bloqueado depois do prazo solicitado.

A função agora devolve o resultado de `block_current` sem essa aquisição
extra. O caminho sinalizado continua adquirindo em
`svc_signal_process_wide_key` e `mutex_release`; o teste de contenção confirma
que sinalizar não permite sair com sucesso antes da transferência do mutex.

Na biblioteca privada antiga inspecionada, a rotina `sdk+0x343ed0` testa
`0xEA01` depois do SVC e chama a rotina de aquisição no ramo de timeout.
Esse achado sustenta a incompatibilidade com o contrato esperado pelo SDK,
mas não demonstra que essa rotina foi alcançada durante a tela preta atual.

Referências públicas comparadas:

- [libnx, condvarWaitTimeout](https://github.com/switchbrew/libnx/blob/master/nx/source/kernel/condvar.c): readquire no código do chamador quando o SVC devolve `0xEA01`. [Licença ISC](https://github.com/switchbrew/libnx/blob/master/LICENSE.md), compatível com o código próprio MIT do projeto.
- [Ryujinx Neo, WaitProcessWideKeyAtomic](https://github.com/Sunshinin11/Ryujinx_Neo/blob/neo-v2-nce2/src/Ryujinx.HLE/HOS/Kernel/Threading/KAddressArbiter.cs): separa timeout da aquisição por sinalização; comparação de comportamento, sem incorporar código.
- [Atmosphère, KConditionVariable](https://github.com/Atmosphere-NX/Atmosphere/blob/master/libraries/libmesosphere/source/kern_k_condition_variable.cpp): conferência adicional da separação entre timeout e sinalização. Nenhum código GPL foi incorporado.

## Testes reproduzíveis

`tests/kernel_condvar_test.c` inclui o `kernel.c` real e usa palavras de
mutex/condição sintéticas e pthreads. Somente o relógio de plataforma é
fornecido pelo teste, usando `CLOCK_MONOTONIC` real. Não há substituição do
kernel, alteração dos prazos ou emulação de sucesso.

| Caso | Kernel da base `107c83c` | Kernel corrigido |
| --- | --- | --- |
| Timeout zero devolve mutex solto | Falha | Passa |
| Timeout finito devolve mutex solto | Falha | Passa |
| Timeout enquanto outro proprietário mantém o mutex | Falha: continua esperando | Passa |
| Timeout após sinalização, ainda aguardando o mutex | Falha: continua esperando | Passa |
| Cancelamento não readquire nem devolve sucesso | Falha | Passa |
| Sinalização com mutex livre | Passa | Passa |
| Sinalização com transferência de mutex | Passa | Passa |

A comparação foi executada extraindo `git archive 107c83c runtime` para um
diretório temporário e compilando o mesmo teste contra as duas versões, sem
trocar a branch nem sobrescrever o checkout.

Comando da regressão:

```bash
python3 tests/test_kernel_condvar.py
```

Resultado no host: **164 testes disponíveis passaram**, incluindo os sete
casos acima e os **109 testes do Mario**. Os 109 fazem parte dos 164, não são
um total adicional. Também executaram os checks C iniciados na importação dos
módulos de teste. O compilador foi Clang 22 via Zig; a compilação freestanding
AArch64 usou o frontend com o triple Android solicitado. Isso não é uma
linkagem de APK com o SDK Android.

O fixture de boot também foi atualizado para fornecer o leitor seguro exigido
pelo observador de recursos e manter seu único registro HLE sob coleta de
seções. A mudança permite voltar a executar os testes de loader, callbacks e
reentradas; não muda o runtime.

A tentativa da suíte geral encontrou quatro módulos indisponíveis neste host:

| Módulo | Limitação |
| --- | --- |
| `test_android_runtime_link` | O driver de link disponível não aceita `-z global`; não foi substituída a verificação do bit ELF. |
| `test_android_window` | Faltam os headers de desenvolvimento JNI. |
| `test_mod_menu` | Falta `javac`. |
| `test_vulkan_gmem` | Faltam SDL3/Vulkan/VMA, ferramentas SPIR-V e ambiente Vulkan de teste. |

Esses módulos foram excluídos explicitamente da rodada de 164 testes.
Não foram verificados o APK final, Bionic/SAF no aparelho ou uma cena do Mario
com o runtime corrigido.

## Compilar no Termux

Na cópia existente do repositório, inclusive quando outra branch estiver aberta:

```bash
bash <<'SH'
set -euo pipefail
cd "$HOME/LASRecomp-Android"
MARIO_BRANCH="android/mario-full-recompiler-test"
git fetch --no-tags origin "refs/heads/$MARIO_BRANCH:refs/remotes/origin/$MARIO_BRANCH"
MARIO_RUNNER="$(mktemp)"
trap 'rm -f "$MARIO_RUNNER"' EXIT
git show "refs/remotes/origin/$MARIO_BRANCH:atualizar-compilar-mario-termux.sh" > "$MARIO_RUNNER"
MARIO_PROJECT="$PWD" bash "$MARIO_RUNNER" /storage/emulated/0/SwitchRoms/Super-extraido
SH
```

O script atualiza somente por fast-forward, mantém arquivos/caches locais,
executa as regressões, reutiliza a biblioteca recompilada existente e chama a
compilação/assinatura nativa. Só gera main/sdk se a biblioteca ou o relatório
estiver ausente. Não solicita novos lotes especulativos de reentradas.

O comando busca o atualizador diretamente da branch remota, mesmo se o arquivo
ainda não existir na branch aberta. O atualizador seleciona a branch do Mario.
Edições de outra branch, incluindo arquivos não rastreados, ficam em um stash
local preservado, com SHA e origem registrados em `.git/mario-update-backups/`;
não são aplicadas ao Mario. Edições do próprio Mario são reaplicadas com o index
preservado após a atualização. Conflitos interrompem a compilação e mantêm o
backup. Caches ignorados pelo Git não entram no stash e ficam protegidos contra
sobrescrita durante checkout/fast-forward. Não há reset, limpeza de caches nem
alteração dos commits da branch de origem.

As regressões do atualizador usam remotos Git locais e um compilador de APK
simulado: `python3 tests/test_mario_termux_update.py`. Verificam checkout a partir
de outra branch, launcher sem o arquivo local, restauração de index/arquivos,
preservação dos caches, conflitos e recuperação após falha no fast-forward.
Esses testes verificam o fluxo Git; não comprovam a compilação Android.

Saída principal:
`build/mario-android-boot/Mario-Recomp-Boot-Test.apk`.
Com Downloads acessível, também:
`/storage/emulated/0/Download/MarioRecomp/Mario-Recomp-Boot-Test.apk`.

O comportamento comprovadamente corrigido é o retorno do timeout e a posse do
mutex. Avançar visualmente além do estado anterior exige executar esse APK.

## Hipóteses restantes e experimento mínimo

| Hipótese | Evidência e limite | Observação mínima que a diferencia |
| --- | --- | --- |
| Bloqueio posterior em sincronização | Os registros iniciais devolvem sucesso, mas sua quantidade é limitada e não representa todas as esperas posteriores. O defeito de timeout corrigido existe, mas não está ligado a um timeout observado no estado preto. | Testar o APK corrigido com a mesma biblioteca e pasta; se continuar preto, obter uma única amostra dos PCs/LRs/WaitKind das threads guest e do proprietário da palavra esperada. Isso separa espera pendente de loop de CPU. |
| Loop/caminho incorreto do código recompilado durante a carga da cena | Há consultas de recursos depois do terceiro present e nenhum trap atual de despacho. Os testes sintéticos não cobrem o executável inteiro. | Se uma thread estiver executável, comparar duas amostras curtas do PC/call stack; conferir as instruções originais e o C gerado apenas no bloco recorrente antes de qualquer reparo. |
| Desenhos descartados pelo NVN | O contador exclui rejeições e existem opcodes sem executor. Não há registro de uso desses opcodes na parada. | Inspecionar os `op_counts` já existentes e `stat_skipped` no estado preto; um opcode sem executor com contagem positiva, ou rejeições de pipeline, identifica um caminho concreto. Zero uso descarta essa explicação nesse ponto. |
| Carga de recurso pendente ou erro de serviço | RomFS e áudio trabalham; há comandos AM respondidos por handlers genéricos. Ausência de fatal não comprova a semântica desses serviços. | Com o PC/stack da thread consumidora, localizar uma única leitura/requisição pendente e verificar seu resultado, tamanho e flag de conclusão; conferir o ramo do guest que depende dessa resposta. Não ampliar stubs nem fabricar sucesso. |

Esses experimentos são próximos discriminadores, não resultados já obtidos
nem uma afirmação de que a tela preta foi resolvida.
