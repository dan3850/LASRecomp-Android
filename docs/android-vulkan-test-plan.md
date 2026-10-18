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
- [ ] T1c — Construir APK no Termux e validar no RedMagic com logs [vk-present], [vk-present-wait], [vk-wait], [mod60-pacer] e FPS real em uma mesma cena. Nao marcar melhora sem dados A/B.
- [ ] T2 — A/B FIFO versus MAILBOX e eventual duplo pacing. Checar modo efetivo e Hz da tela antes de mudar sleep. Nao desativar cap Stable60 em tela 120/144 Hz sem garantia de velocidade correta.
- [ ] T3 — A/B SUBS=8 contra 16; testar somente se [vk-wait] indicar espera importante por ring slot. Mudanca implica mais buffers/recursos em voo.
- [ ] T4 — Otimizar transicoes de layouts GENERAL e duracao de render passes; so usar DONT_CARE em depth comprovadamente descartavel. Preservar todas as dependencias de leitura/copia/feedback.
- [ ] T5 — Medir BCn/ASTC repetido antes de mudar texturas. Ja existe imagem residente, amostragem e hash; nao duplicar cache existente.
- [ ] T6 — Revalidar FPS, frame time, upload, imagens de casas, audio e estabilidade no outdoor; guardar ganho ou regressao documentado por commit.

## Ordem fixa e coleta

1. Finalizar T1c primeiro, sem aplicar T2/T3/T4 simultaneamente.
2. Comparar mesmo save, mesma resolucao e modo de tela, opcao Stable60 identificada.
3. Se slot-total for alto: inspecionar o reuso de frames/submissao; se acquire-total for alto: investigar compositor/present; se ambos baixos: inspecionar processamento, upload, GMEM.
4. Registrar por teste: commit, estado, medidas antes/depois, observacao de velocidade, artefatos visuais e decisao de manter/reverter.
5. So entao avancar T2/T3/T4. Cada teste deve ser reversivel na mesma branch.

Observacoes: o log antigo "acquire blocked" media a chamada inteira vk_frame_begin, nao somente vkAcquireNextImageKHR. O contador novo distingue slot e acquire. O campo upload ja relatado mede bytes copiados/alocados no ring, NAO e taxa de banda fisica de LPDDR nem exclusivamente decodificacao de texturas. LARECOMP_VK_COUNTER=virtual nao e metodo valido para comprovar FPS real. Um export no shell Termux nao altera automaticamente variaveis de ambiente do APK Android.