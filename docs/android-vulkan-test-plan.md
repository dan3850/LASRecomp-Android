# LASRecomp Android — checklist fixo de testes Vulkan

BRANCH UNICA: android/vk-wait-breakdown-no-headstart.
Base registrada: 3b6cbcc39f4f649411dcbf7e56ff578afc1e18c0.
Nao criar branches para cada teste. Preservar historia, liblasgame.so privada, saves, cache do Termux e APK anterior para comparacao.

Aparelho de validacao: RedMagic 11 Pro / Adreno 840.
Cenas: casa, primeira entrada em outra casa, mapa externo.
Aceitacao: FPS real e velocidade normal, imagem completa, sem fechamento, audio sem estalos e sem novo engasgo.

## Checkpoints

- [x] T0 — Conferir codigo e propostas da outra IA. O mod Stable60 tem sleep no host, mas ele so atua quando esta ativo; o modo de presentacao real precisa ser verificado. O codigo ja pede minImageCount+1 imagens (com limites), possui tres slots de frame e protege seu reaproveitamento por timeline. O cache de texturas ja evita repeticao de decode BCn quando hash nao muda.
- [x] T1a — Instrumentar separadamente espera do slot e espera na chamada de acquire Vulkan. Arquivos: runtime/nvn/vulkan/device.c e present_wait_stats.h. Saida: [vk-present-wait] a cada 2 s, [vk-present] com modo efetivo e imagens reais. Sem mudar pacing, clocks, imagens, fences ou jogo.
- [x] T1b — Teste unitario do contador de tempos compilado e executado em clang no ambiente de desenvolvimento: TEST_VK_PRESENT_WAIT_PASS. Repetir no Termux antes do APK.
- [x] T1c — APK testado no RedMagic. Arquivo LASRecomp-grafico-20261018-202450.zip: MAILBOX real, 5 imagens efetivas, 22 relatorios [vk-present-wait], 2435 frames, slot-total=3.6ms, acquire-total=43.3ms. Nenhuma chamada acima de 16.67ms. FPS mediano nos registros [vk] = 55.4 (mistura cenas; nao interpretar como FPS outdoor exclusivo).
- [x] T2a — Hipotese de FIFO/duplo bloqueio no acquire descartada PARA ESTE TESTE: presentacao MAILBOX, acquire ~0.018ms por frame. Nao desativar pacing Stable60 sem garantir velocidade correta.
- [ ] T2b — So comparar FIFO se algum aparelho/execucao usar FIFO de fato.
- [x] T3 — Aumento do ring descartado PARA ESTE TESTE: ring slot ~0–1ms por 2s; nao ha justificativa para subir SUBS de 8 para 16/24.
- [x] T4a — Identificado gargalo: compute -> CPU snapshot (pending), aproximadamente 0.97–1.20s por 2s no mapa externo. Esses waits precisam ser classificados; nao e prova de que todos sao dispensaveis.
- [x] T4b — Implementada filtragem reversivel de preflight em exec.c: LARECOMP_VK_PREFLIGHT_USED_ONLY=0 restaura o caminho anterior. So remove verificacoes de buffers nao referenciados; GMEM indireto, CPU HLE, indices, texturas, estados e fences protegidos. Teste puro de selecao passou em clang no ambiente de desenvolvimento.
- [ ] T4c — Comparar APK anterior (T1 commit c2c567e) com APK novo (T4b) no RedMagic. Confirmar FPS, esperas, grafico completo, audio e velocidade. Nenhum ganho comprovado ainda.
- [ ] T4d — Depois de T4c investigar layouts GENERAL, render pass LOAD/STORE; DONT_CARE so quando conteudo realmente descartavel.
- [ ] T5 — Medir BCn/ASTC repetido antes de mudar texturas. Ja existe imagem residente, amostragem e hash; nao duplicar cache existente.
- [ ] T6 — Revalidar FPS, frame time, upload, imagens de casas, audio e estabilidade no outdoor; guardar ganho ou regressao documentado por commit.

## Ordem fixa e coleta

1. T1 concluido no aparelho. Proximo: T4c, comparar o APK T1 e o APK T4b sem combinar mudancas de layout, ring ou mod60.
2. Comparar mesmo save, mesma resolucao e modo de tela, opcao Stable60 identificada.
3. Nesta sessao slot/acquire quase zero; medir agora compute -> CPU snapshot, especialmente verificacoes de uniform buffers e vertex streams nao utilizados.
4. Registrar por teste: commit, estado, medidas antes/depois, observacao de velocidade, artefatos visuais e decisao de manter/reverter.
5. So entao avancar T2/T3/T4. Cada teste deve ser reversivel na mesma branch.

Observacoes: o log antigo "acquire blocked" media a chamada inteira vk_frame_begin, nao somente vkAcquireNextImageKHR. O contador novo distingue slot e acquire. O campo upload ja relatado mede bytes copiados/alocados no ring, NAO e taxa de banda fisica de LPDDR nem exclusivamente decodificacao de texturas. LARECOMP_VK_COUNTER=virtual nao e metodo valido para comprovar FPS real. Um export no shell Termux nao altera automaticamente variaveis de ambiente do APK Android.
## Resultado T1 — ZIP 2026-10-18 20:24:50

- RedMagic 11 Pro, Adreno 840, Android 16; host_import=0. Swapchain MAILBOX, actual_images=5, requested_images=5, surface_min=4.
- 22 logs [vk-present-wait], 2435 frames no total: 3.6ms somados em slot e 43.3ms em acquire; 0 eventos >=16.67ms.
- Mediana 55.4 FPS em 329 janelas [vk] do ZIP. Mistura cenas e reinicializacoes; nunca afirmar que isso descreve so outdoor.
- [vk-wait] indica ~970–1200ms / 2s em compute -> CPU snapshot (pending); ring slot geralmente 0–1ms / 2s.
- Mod Stable60 ativo, marcadores de aplicacao executados. Timestamp source=gpu. O sleep do mod variou e em varias janelas foi 0ms; evitar atribuir todo gargalo ao pacer.
- T4b ja implementado: reduzir verificacoes de ranges CPU que o shader nao le; A/B contra T1 e obrigatorio antes de aprovar.
