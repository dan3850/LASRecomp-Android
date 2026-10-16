# Vulkan: reutilização de buffers e contadores entre submissões

Base examinada: `5f320586902a103dff3d8a76bfb3263c100dcac6`, branch
`android/external-game-folder`.

Durante a investigação, a branch avançou com `49d9f8c` (snapshots GMEM) e
`c6516c8` (diagnóstico de timestamps). Essas alterações foram preservadas.
A correção de timestamps abaixo já veio de `c6516c8`; este incremento
adiciona apenas as duas otimizações de buffers e seu teste de regressão.

## Evidência e limites

O relato no RedMagic 11 Pro é 60 FPS na casa e 20–30 FPS no exterior,
~460 MB de `upload` e ~900 ms de espera por intervalo de dois segundos.
Esses valores foram fornecidos pelo usuário; não houve execução do jogo
nesse aparelho neste trabalho.

`stat_upload_bytes` soma os tamanhos pedidos a `vk_transient()`. Inclui
snapshots de vértices/índices, uniformes, tabelas GMEM e staging de texturas;
não é uma medida de tráfego físico da GPU. Após `49d9f8c`, também inclui
cópias para snapshots GMEM persistentes, mas não todas as alocações persistentes. O total não prova uploads duplicados de texturas.

`stat_wait_ns` soma chamadas de espera por timeline, inclusive de threads
que podem se sobrepor. Não representa, isoladamente, duração de execução da
GPU por frame. Há esperas necessárias para copyback de compute, leituras
CPU, reutilização de recursos e fences. Não foram removidas.

O exterior possui caminhos de preparação de muitos desenhos, snapshots de
memória global sem host import, cópias de constantes/geometria e múltiplos
passes. O código possui barreiras ALL_COMMANDS entre passes, cópias e
compute. Sem identificar dependências e tempos por passe no aparelho,
não há evidência suficiente para estreitá-las preservando os gráficos.
A causa dominante dos 20–30 FPS continua não comprovada.

## Correções pequenas

1. `guest_copy`: indexar pelo endereço e aceitar prefixos de uma cópia
   maior na mesma submissão. Antes, pedidos de tamanhos diferentes do mesmo
   endereço criavam cópias distintas. Mantém a invalidação por submissão e
   atualização inline/compute. Não aumenta o tamanho lido do jogo.
2. Cache de vértices: quando endereço e tamanho são iguais e a GPU já
   concluiu o uso, atualizar a alocação mapeada existente em vez de destruir
   e recriar VkBuffer/VMA. Comparação integral dos bytes e flush continuam.
   Mudanças em buffers ainda em uso usam outro snapshot, sem espera nova.
3. Diagnóstico `paired`: preservar o registro anterior entre submissões e
   resolver os slots em ordem de sequência, inclusive quando o anel volta
   ao início. Usar diferença dos timestamps brutos evita incluir mudanças
   na calibração CPU/GPU no diagnóstico. Endereços adjacentes continuam
   sendo apenas um par reconhecido; não provam um frame inteiro. `paired=0`
   também pode indicar endereços não adjacentes, e não GPU sem trabalho.

Nenhuma alteração de FPS, vsync, relógio sintético, shader, efeito, áudio,
controle ou quantidade de desenhos. Não altera os modos de teste de pacing.

## Validação

`tests/test_vulkan_gmem.py`, Clang 20 e Vulkan Lavapipe/llvmpipe:

- 101 pedidos (8192 bytes seguido por 100 prefixos de 4096) alocam somente
  8192 bytes no ring; invalidação preserva os dados antigos.
- Buffer de vértices modificado enquanto em uso não é sobrescrito; após
  conclusão, a alocação original é reutilizada.
- Queries Vulkan reais em dez submissões atravessam a volta do anel e
  produzem dez reports e nove intervalos adjacentes; endereço não adjacente
  não cria um par.
- O teste GMEM integrado confirma 1 MiB copiado em 61 submissões com
  snapshots persistentes, contra 61 MiB no caminho antigo (carga sintética).
- 13 casos de LDG/STG, writeback seletivo, snapshots GMEM, limites do pool
  e atualização de atlas R8 dentro do mesmo frame: PASS.
- Suíte Python: 49 testes unittest passaram; dois módulos de teste ficaram
  indisponíveis sem JDK (`test_android_window`, `test_mod_menu`). O harness
  Vulkan também passou durante a descoberta da suíte.

Não foi compilado APK neste ambiente Linux; o script existente compila e
assina no Termux reutilizando os objetos e as dependências locais:

```bash
cd "$HOME/LASRecomp-Android" &&
[ "$(git branch --show-current)" = "android/external-game-folder" ] &&
bash ./compilar-lasrecomp-pasta-externa.sh
```

Saídas: `/storage/emulated/0/Download/LASRecomp/`, APK assinado e ZIP de
fontes nomeados com o commit. Nenhuma regeneração de `liblasgame.so` é
necessária para estas mudanças do renderer. Se uma biblioteca privada de
teste força intervalo/60 FPS, ela precisa ser desativada/substituída pela
original para comparar desempenho e velocidade corretos; atualizar só o
APK não desfaz esse patch privado.

A validação de ganho exige comparar a mesma posição do mapa externo no
aparelho, com a biblioteca original e as mesmas opções/resolução/temperatura.
Nenhum resultado deste teste de software demonstra 60 FPS no Zelda.
