# D24 isolado: regressao recebida e integracao restrita

Checkpoint de 2026-10-24, continuando `cf594a6`. O usuario reportou melhora
parcial, novos defeitos graficos, fechamento e congelamento da imagem. A
primeira integracao D24 **nao foi aprovada**; nao chamar seu teste de sucesso
global nem atribuir os encerramentos a uma causa ainda nao registrada.

## Nova evidencia recebida

- `Zelda-efeitos (1).zip`, SHA256
  `1e099d0dff3e097548db2b4c65d3f26064c457df8879ea0e03a67f18e613f791`.
- `Zelda-SNX-boot (1).txt`, SHA256
  `9c102c93144cef223af4efd5ef465458c06cb06253c0605c0344b30b21cbc10d`.
  E identico ao log dentro do ZIP; nao contar como duas execucoes.
- Revisao `cf594a6`, tradutor ScarletNX, D24 solicitado/suportado/habilitado,
  faixa de profundidade e ports anteriores ON, GPU DETALHADA e captura de
  efeitos ON. A sessao e `000001a16fad19e4`.

| Frame | Cena/resolucao | Attachment / sampled | Pixels iguais / diferentes |
|---|---|---|---|
| 723 | exterior, 1280x720 | `54da60000` / `550d10000` | 921600 / 0 |
| 1899 | casa do telefone, 1920x1080 | `54da60000` / `550d10000` | 2073600 / 0 |
| 2734 | casa, 1280x720 | `54c980000` / `5504a0000` | 921600 / 0 |

As tres imagens amostradas agora contem geometria, sem zeros, NaN ou valores
fora de 0..1. Comparacao com mascaramento correto dos bits altos indefinidos
D24: todas coincidem exatamente com os attachments capturados. Isso confirma
que a entrada antes zerada mudou, sem provar que toda luz/composicao esta
correta. `producer_relationship` continua explicitamente `unproven`: o ZIP
nao e um trace completo dos pacotes DMA.

Quinze janelas somam 75.128321 segundos, **18532 exportacoes e 15349044960
pixels convertidos**, nenhuma falha registrada. Aproximadamente 246.7
exportacoes/s e 204.3 milhoes de pixels logicos/s. Ha alvos exportados mais
de uma vez com o mesmo wgen no mesmo frame. Estes sao contadores de trabalho,
nao bytes fisicos de DRAM, ganhos ou uma comparacao controlada de FPS.

O profiler detalhado tambem mostra tempo significativo entre passes com
copias. A captura armada impede comparacao de FPS pelo analisador, como
previsto. Nenhuma traducao JIT nova explica esse trecho.

O log inclui `Exit.` aos 88 segundos, sem fatal Vulkan, device-lost ou stack
de crash que identifique o fechamento reportado. O bloco completo de
telemetria termina antes disso, por volta de 78.67 s. Os trechos de startup
mostram tentativas historicas; nao atribuir uma delas a esta sessao sem
timestamp/motivo. O relato de congelamento/fechamento continua valido, mas
a causa especifica nao esta estabelecida por esse arquivo.

## Problemas encontrados na primeira integracao

1. `flush_bytes` foi ampliado para D24. Essa funcao nao atende apenas DMA/2D:
   tambem alimenta `surf_flush`, `rt_flush_older`, `vk_rt_before_write` e
   observadores CPU/retorno a memoria. A alteracao ativava esses caminhos
   globais para alvos anteriormente excluidos.
2. A lista de alvos pendentes verifica wgen/ordem das imagens, mas nao rejeita
   ali uma escrita de memoria mais recente no alvo D24 ou em um alias fisico.
   Depois de `vk_guest_read` fornecer bytes atuais de um recurso owned, uma
   imagem D24 antiga poderia ser sobreposta a eles. Agora ha um teste do
   codigo real de selecao que preserva esse owned mais recente.
3. Cada exportacao refazia image-to-buffer e empacotamento, mesmo para o
   mesmo conteudo, e usava o scratch global tambem emprestado por DMA/blit e
   upload. O crescimento/substituicao desse scratch e sua vida util passavam
   a participar de mais chamadas aninhadas. Nao ha prova de que isso causou
   o crash; isolar o workspace remove essa interacao e permite reuso seguro.

Esses problemas de alcance/integracao sao verificaveis no codigo. Os testes
anteriores provavam a conversao dos bits e execucao do componente, mas nao
estabeleciam a correcao de todos esses observadores no jogo/Adreno. Nao
repetir a validacao do componente como prova de estabilidade Android.

## Correcao entregue

- `flush_bytes` e `flush_record` voltam exatamente a politica anterior.
  D24 novo entra somente em `rt_pending_over(..., d24_overlay=1)`, usado por
  `vk_rt_overlay`. Readbacks, escrita de retorno e CPU before-write usam 0.
  Os formatos que ja eram suportados preservam seu caminho.
- A superficie D24 deve estar totalmente contida na copia e ainda pendente;
  `gpu_mem_dirty_since(s->gw, ...)` rejeita escrita posterior de memoria,
  inclusive aliases fisicos registrados pelo mecanismo existente. Caso
  parcial/incompativel fica na politica anterior; nao se inicia readback D24
  para contornar essa restricao. Nao se removem verificacoes existentes.
- A lista continua unica e ordenada por `wseq`: novos alvos D24 e alvos de
  cor nao sao compostos em listas separadas que poderiam inverter sua ordem.
- Um workspace privado retido, no maximo 64 MiB, usa `VkOwnRes` existente
  para alocacao/retirada apos fence. Nunca e publicado como memoria guest
  nem usa `vk_bl_scratch`. Crescimento so apos alocacao nova bem sucedida;
  o anterior permanece protegido pelas funcoes normais de aposentadoria.
- Cache de **uma conversao**, por imagem, wseq, wgen, epoch, formato e
  dimensoes. Se o conteudo muda, converte novamente; todo consumidor ainda
  recebe sua copia/swizzle. Barreiras ordenam os leitores antes de sobrescrever
  o workspace, mesmo quando uma versao nova e gravada no mesmo command buffer.
  Nao ha wait/submit extra, descarte de desenho ou mudanca do clock/AOT.
- O GLSL e o empacotamento exato depth/stencil permanecem os mesmos da
  versao anterior. As qualificacoes de formato, dimensoes, alinhamento e
  limites continuam conservadoras; o shader interno antigo continua recusado.

`SNX_D24_PACK_META_V1` agora inclui `integration=2`, `gpu_overlay_only=1`,
`cpu_writeback=0`, `isolated_work=1`. Na janela, `packed` conta exportacoes;
`conversions` e `pixels` contam conversoes efetivas; `reused` conta reuso.
`stale_rejected` e `partial_rejected` contam decisoes de selecao, podendo
incluir repetidas tentativas sobre o mesmo alvo. Nao sao FPS ou DRAM fisica.

A preferencia nova e `zelda_d24_copies_v2`, **OFF por padrao**. O ON salvo
da versao 1 nao a ativa. A UI mostra **Copias D24 isoladas (teste)** apenas
no perfil D24. O usuario pode fazer um ensaio ON e voltar ao comportamento
anterior em OFF, sem perder a faixa de profundidade nem os ports aceitos.

## Encerramento: diagnostico existente compartilhado com Zelda

`MarioBootActivity` ja consultava o historico `ApplicationExitInfo`; o
launcher do Zelda e seu exporter nao o faziam. O coletor foi extraido para
`ScarletNxExitInfo`, compartilhado pelos dois. `Salvar log` do Zelda agora
inclui `mario-exit.log`, com timestamp, PID, motivo/status, processo, descricao
e PSS/RSS informados pelo Android, ate oito entradas do **proprio pacote**.

O child do Zelda registra uma vez um process-state summary curto com
`D24-integration=2 requested=... perf=...`; esse campo e solicitacao, nao
prova de que Vulkan habilitou o modo. Pode ser associado ao encerramento
retido pelo sistema. Nao atribuir um crash historico antigo a um teste novo.

O trace de um crash nativo ou ANR do `:snx`, quando o sistema o disponibiliza,
e preservado ate 48 KiB em base64, com limite/truncamento explicito. Tombstone
nativo pode ser protobuf: nao inserir bytes binarios diretamente num log UTF-8.
Nao pede permissoes adicionais e nao coleta dados de outros aplicativos.
Nao ha consulta por frame nem alteracao de sinais/fault handlers. API
indisponivel nao bloqueia o jogo ou a exportacao. Fonte da API: AOSP Android16
[`ActivityManager`](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-16.0.0_r1/core/java/android/app/ActivityManager.java)
e [`ApplicationExitInfo`](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-16.0.0_r1/core/java/android/app/ApplicationExitInfo.java).

## Verificacoes

- 66 testes de auditoria, zero skips com compilador/validador SPIR-V reais.
- Selecao/gravação C real: politica CPU original, rejeicao de memoria mais
  recente, contencao parcial, ordem comum cor/D24, cache e invalidacao por
  nova escrita/epoch, limites e falhas. ASan/UBSan passaram; leak scan
  permanece indisponivel por restricao de `/proc` deste host.
- Vulkan real no **driver de software llvmpipe LLVM15 do host**:
  **47930724 pixels**, dois formatos, linear e GOB bh0/1/4, 59 reusos e 14
  conversoes no fixture. Copias consecutivas e versao nova da imagem no
  mesmo command buffer preservam as duas versoes e todos os paddings.
- Adapter/export Java real executado com endpoints Android simulados:
  escopo do pacote, motivo/status, ordem das entradas, resumo, bytes de
  trace exatos/limitados, trace nulo e historico vazio. Isso nao simula a
  producao do motivo real pelo Android.
- Pilha reversivel, tres C units completas, parsing das cinco classes Java
  afetadas, sintaxe shell/Python e whitespace verificados.

Nao houve execucao do APK/jogo na Adreno. Nao declarar que o crash,
congelamento ou todos os defeitos graficos estao resolvidos, nem ganho de FPS.

## Termux e teste seguinte

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-copias-profundidade-termux.sh
```

Saida distinta: `Download/ZeldaRecomp/Zelda-SNX-COPIAS-ISOLADAS.apk`.
O builder valida tambem os marcadores da integracao 2. Preserva a versao
de efeitos anterior como `Zelda-SNX-COPIAS-V1-ANTES-ISOLADAS.apk`, uma vez;
o backup bom `Zelda-SNX-EFEITOS-ANTES-COPIAS.apk` continua guardado.
Reutiliza AOT, CMake/Ninja/Gradle/LLVM e caches; nenhum clean.

O novo APK inicia com D24 isolado OFF. Para ensaiar a correcao, mudar somente
**Copias D24 isoladas (teste) ON**, **Preservar faixa de profundidade ON**,
ports anteriores como antes, Ryujinx OFF, FPS LEVE, **todas as capturas OFF**.
Iniciar outro processo e percorrer as mesmas cenas. Nao pedir outro ZIP de
pixels agora: o ultimo ja confirmou a copia em tres pares.

Se fechar: reabrir o launcher e usar Salvar log antes de iniciar outra
tentativa, para preservar o motivo/trace do processo correto. Se congelar
e for necessario encerrar manualmente, declarar essa acao: o sistema pode
registrar fechamento solicitado, sem identificar a causa do congelamento.
Voltar apenas D24 isolado OFF e reiniciar se regredir; manter profundidade ON.

**Falta:** verificar estabilidade/artefatos desta integracao na Adreno,
classificar o encerramento real se repetir, identificar efeitos residuais
de luz/sombra/nevoa/blur depois da entrada de profundidade correta e medir
OFF/ON LEVE comparavel. O pipeline de hashing sob EACCES e frame pacing
continuam trabalho posterior. Nao reabrir a correcao aceita de cores/agua.
