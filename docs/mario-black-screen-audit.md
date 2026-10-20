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

### Falha da fixture no Termux

Na execução ARM64 enviada após `98e314d`, os sete testes do kernel passaram,
mas duas execuções da fixture de boot terminaram com código `3`. Esse retorno
identifica a reserva de uma janela sintética de memória, antes de `loader_load`,
`dispatch_init` ou callbacks guest. A linha `[mods] ... unsupported` aparece
durante o carregamento da biblioteca e não é a mensagem de erro desse retorno.
O log antigo não registra `errno`, portanto não distingue colisão de endereço
de incompatibilidade com a flag de mapeamento.

A fixture foi corrigida para reservar os endereços antes de `gamelib_load`,
seguindo a ordem de reserva/carregamento do aplicativo. Usa uma indicação de
endereço com conferência estrita do endereço retornado, sem flags que substituam
mapeamentos existentes e sem depender de `MAP_FIXED_NOREPLACE`. Reservas em
endereço diferente são desfeitas e causam falha explícita. Os dois testes novos
simulam uma alocação durante `dlopen` e uma colisão pré-existente; continuam
executando o loader e o dispatcher reais e verificam que a memória ocupada não
é sobrescrita. A mudança afeta somente os testes, não a execução do jogo.

No host, os dez testes de bootstrap passaram. O teste de alocação durante
`dlopen`, executado contra a fixture anterior de `98e314d`, reproduziu o retorno
`3` com a mesma linha `[mods]`. Isso demonstra o defeito de ordem da fixture,
mas não identifica o motivo específico do `mmap` no aparelho, pois faltava o
erro da chamada naquele log. A nova execução no Termux e o APK seguem pendentes.

No teste ARM64 de `28241f7`, os callbacks passaram, mas outra execução informou
`fixture guest mapping at 7000000000 failed: File exists` antes de carregar a
biblioteca. Na fixture anterior, essa mensagem também representava um endereço
retornado diferente do solicitado; a nova mensagem distingue isso de um erro
real de `mmap`. Reservar antes de `dlopen` não evita colisões com mapeamentos do
próprio executável e suas dependências, já carregados antes de `main` pelo
sistema. A fixture agora identifica exclusivamente essa colisão e pode iniciar
um novo processo de teste, obtendo uma nova distribuição ASLR, até oito vezes.
Não usa `MAP_FIXED`, não sobrescreve o mapeamento ocupado e não muda o runtime,
o timing ou a sincronização do jogo. Só aceita sucesso se o teste executar de
fato suas verificações; oito colisões continuam sendo falha. Erros do loader,
guest, callbacks e outros erros de memória não são repetidos nem ignorados.
Quatro regressões verificam essas regras de execução.

## Compilar no Termux

No worktree já usado pelo Mario (`~/LASRecomp-Mario-Teste` neste ambiente).
Isso evita tentar abrir a mesma branch em um segundo worktree do Zelda:

```bash
bash <<'SH'
set -euo pipefail
cd "$HOME/LASRecomp-Mario-Teste"
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

### Captura acionada durante a tela preta

O APK do Mario oferece **Capturar estado** sobre a tela do jogo. Toque depois
que a tela permanecer preta, espere a confirmação de gravação e volte ao
launcher para **Salvar log**. O arquivo exportado começa por `mario-threads.log`,
separado do áudio e sem depender dos últimos 160 KB de `lasrecomp.log`.

O coletor obtém duas amostras com aproximadamente 100 ms entre elas. No Android
ARM64, `native_pc` e `native_lr` vêm do contexto nativo interrompido por um
sinal; os offsets relativos às bibliotecas permitem localizar código com ASLR.
`guest_dispatch_pc` é o alvo salvo no `Cpu`, que pode estar desatualizado em um
loop: **não é anunciado como PC exato da instrução guest**. O relatório inclui
LR/SP guest, último SVC e argumentos, indicação de SVC ainda ativo, estado de
espera, palavra do mutex e proprietário quando a região é legível, e objetos
de `WaitSynchronization`. O cabeçalho identifica HEAD e biblioteca recompilada.
Metadados de espera são lidos separadamente sob o lock do kernel, portanto não
representam uma parada simultânea de todas as threads.

O handler não executa I/O, alocação, simbolização, locks nem resolução de TLS
do motor. Copia o contexto da própria thread para slots atômicos lock-free; o
coletor faz a gravação/simbolização depois. Um handler preexistente de `SIGURG`
impede a captura, em vez de ser substituído. Respostas ausentes aparecem como
`sampled=0`; não são preenchidas com registros antigos. O coletor tem limites
de tempo para respostas/lock e limite explícito de 256 threads. Não sinaliza
objetos Horizon nem muda resultados, deadlines, escalonamento ou flags de
sincronização. Há perturbação breve inerente à amostragem por sinal; o intervalo
entre amostras pertence somente ao coletor. A exclusão com teardown mantém os
objetos de thread válidos, e a ponte JNI aguarda chamadas em andamento antes de
liberar o callback do motor.

Os testes usam pthreads e sinais reais: loop sem dispatcher, espera de condvar
com outro proprietário, evento não sinalizado, resposta ausente, handler
preexistente, captura concorrente, lock ocupado, leitura limitada a regiões e
vida útil do callback JNI. O script Termux executa essas regressões antes do
build e verifica a exportação do símbolo nativo. A ABI `Cpu` e a biblioteca
privada do jogo não são alteradas. Esta entrega torna o experimento executável;
não é apresentada como correção da tela preta.

Validação no host: 192 testes disponíveis aprovados, incluindo os dez testes
da captura e da ponte. O caminho de contexto AArch64 também compilou para um
objeto Linux/glibc, sem executar esse objeto. Isso não substitui linkagem com
Bionic, compilação Java/SDK nem execução do APK. Os quatro módulos Android/
Vulkan indisponíveis continuam sendo os listados acima. A confirmação no
aparelho é a presença das duas amostras e da identidade no arquivo exportado;
o conteúdo dessas amostras será usado para investigar a causa, ainda pendente.

| Hipótese | Evidência e limite | Observação mínima que a diferencia |
| --- | --- | --- |
| Bloqueio posterior em sincronização | Os registros iniciais devolvem sucesso, mas sua quantidade é limitada e não representa todas as esperas posteriores. O defeito de timeout corrigido existe, mas não está ligado a um timeout observado no estado preto. | Testar o APK corrigido com a mesma biblioteca e pasta; se continuar preto, obter uma única amostra dos PCs/LRs/WaitKind das threads guest e do proprietário da palavra esperada. Isso separa espera pendente de loop de CPU. |
| Loop/caminho incorreto do código recompilado durante a carga da cena | Há consultas de recursos depois do terceiro present e nenhum trap atual de despacho. Os testes sintéticos não cobrem o executável inteiro. | Se uma thread estiver executável, comparar duas amostras curtas do PC/call stack; conferir as instruções originais e o C gerado apenas no bloco recorrente antes de qualquer reparo. |
| Desenhos descartados pelo NVN | O contador exclui rejeições e existem opcodes sem executor. Não há registro de uso desses opcodes na parada. | Inspecionar os `op_counts` já existentes e `stat_skipped` no estado preto; um opcode sem executor com contagem positiva, ou rejeições de pipeline, identifica um caminho concreto. Zero uso descarta essa explicação nesse ponto. |
| Carga de recurso pendente ou erro de serviço | RomFS e áudio trabalham; há comandos AM respondidos por handlers genéricos. Ausência de fatal não comprova a semântica desses serviços. | Com o PC/stack da thread consumidora, localizar uma única leitura/requisição pendente e verificar seu resultado, tamanho e flag de conclusão; conferir o ramo do guest que depende dessa resposta. Não ampliar stubs nem fabricar sucesso. |

Esses experimentos são próximos discriminadores, não resultados já obtidos
nem uma afirmação de que a tela preta foi resolvida.

### Captura real de e0aafba: espera pelo evento 0x13f

O relatório do aparelho identifica a biblioteca
`mario-full:7c753446ca473fbd66a2e5eb` e duas amostras separadas por cerca de
102 ms. Em ambas, a thread principal 80/handle 0x101 está em SVC 0x18
(`WaitSynchronization`), com um único evento 0x13f não sinalizado e timeout
infinito. O despacho salvo é SDK+0x3438e0, LR SDK+0x343968 e SP
0x723ffff6b0. A inspeção privada da função recompilada confirma a chamada ao
wrapper do SVC; esse LR pertence à função de espera, não identifica seu
chamador no Mario. `wait_addr` nessa linha é resíduo de uma espera anterior,
pois `wait=none` e `sync_wait=1`; não é evidência de mutex bloqueado.

Isso localiza uma espera pendente durante a tela preta, mas não prova sua
causa nem bloqueio permanente. Os logs disponíveis não registram a origem
do evento ou a pilha acima dessa função. Os eventos AM/HID sem produtor são
candidatos, mas notificações de mudança podem permanecer legitimamente
sem sinal: não há evidência para sinalizá-los artificialmente.

O schema 2 acrescenta origem por objeto (thread, PC/LR e contexto de serviço/
comando IPC), número de chamadas a `kernel_signal`, último sinalizador e
resets via SVC. A origem é preservada quando outro handle aponta ao mesmo
objeto; ela não é deduzida da ordem numérica dos handles. Sinalizador zero
representa produtor host. Os resets contados são somente os SVCs, não todas
as limpezas internas dos serviços.

Na espera de sincronização, o coletor também lê até 16 frames encadeados,
apenas em regiões registradas legíveis, com alinhamento, limites e avanço
monotônico. Mantém o lock que impede a thread de retornar da espera, confere
SP/FP contra a amostra e não lê memória arbitrária no handler de sinal.
Frames omitidos pelo compilador podem limitar o resultado; LRs salvos não
constituem por si só prova de chamada executada. A ABI `Cpu` e os arquivos
privados recompilados permanecem iguais.

O experimento mínimo é iniciar novamente o APK, capturar durante a tela
preta e exportar o log: `event0_origin` identifica o produtor a auditar e
`frameN` localiza o chamador. `signals0` separa ausência de sinalização de
um evento que já foi sinalizado e depois limpo. Esta mudança continua sendo
um experimento direcionado, não uma correção funcional da tela preta.

Validação desta extensão: 192 testes disponíveis aprovados no host. O teste
de evento passa pelo codec/dispatcher IPC de produção, verifica serviço e
comando, restauração do contexto externo, preservação da origem no segundo
handle, frames sintéticos e ausência de despertar durante a captura.
Os quatro módulos Android/Vulkan indisponíveis continuam excluídos pelos
motivos já documentados; não foi compilado nem executado um novo APK aqui.

### Regressão de layout introduzida em ee7edde

O relatório seguinte identifica ee7edde, mas a captura tem zero threads na
primeira amostra e apenas a principal na segunda. O fim do log registra três
SIGSEGVs em `f_7004344590`, acesso a 0x1b0, LR guest 0x7004144984, antes dos
callbacks de inicialização. O último SVC é GetThreadPriority (0x0c), com
handle de entrada zero, apesar do handle da thread principal ser 0x101.
Os três presents registrados no arquivo não comprovam progresso nessa
execução: o arquivo agrega sessões anteriores.

A extensão de KObject em ee7edde mudou seu tamanho de 12 para 136 bytes,
deslocou KThread.cpu de 16 para 144 e KThread.handle de 1072 para 1200.
Isso quebrou a compatibilidade com callers compilados com o layout anterior.
Em um experimento sintético com o header real de ee7edde e leituras pelos
offsets anteriores, o handle e o callback foram lidos como zero (exit 1);
com o layout restaurado, retornaram 0x101 e 0x7080000040 (exit 0).
Esse mecanismo reproduz a entrada inválida observada. Sem inspecionar o
APK novo, a presença exata de objetos antigos nele não foi verificada.

A correção mantém os metadados dos eventos em uma tabela separada por
identidade do objeto, protegida pelo lock existente; restaura KObject e o
prefixo de KThread; e acrescenta novos campos de thread somente no final.
Asserts impedem novo deslocamento do prefixo. A capacidade da tabela de
diagnóstico não interfere em sinalização nem alocação de handles.

O build Mario agora inclui o conteúdo de kernel.h na chave dos objetos do
runtime, além dos depfiles. A atualização recompila o runtime afetado sem
apagar caches, reconstruir a biblioteca privada ou baixar dependências por
esse motivo. Os testes verificam acesso por offsets antigos e sinalização
mesmo com a tabela de diagnóstico cheia. A confirmação de que o crash
sumiu depende do APK no aparelho; esta correção de regressão não demonstra
a resolução da espera original no evento 0x13f.

Validação da correção de layout: 194 testes disponíveis aprovados no host,
incluindo os 12 da captura; verificação sintática do script e do diff
aprovadas. Os mesmos quatro módulos Android/Vulkan permanecem indisponíveis.
