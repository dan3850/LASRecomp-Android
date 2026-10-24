# Copias exatas da profundidade D24: evidencia e teste no Android

Checkpoint: 2026-10-24. Continuacao de `5711117`, preservando o Stable60, os
ports de desempenho e a correcao de faixa de profundidade aprovada em `9be351c`.
Esta entrega implementa uma lacuna concreta nas transferencias. A recuperacao
da nevoa/luz e o custo no RedMagic ainda precisam de confirmacao no aparelho.

## O que chegou do aparelho

`Zelda-efeitos.zip`, SHA256
`29bdbf04133b81617840e6b956c65b7e24eacff6c0bf99690214704703c5492d`,
contem tres pares completos da sessao `000001a16f81d032`. O log separado
`Zelda-SNX-boot.txt`, SHA256
`d64c909f407d32f5ef7f57b8568e3311a0d3eb72c0f2090e5c203792f47de944`,
e identico ao log dentro do ZIP: e **uma execucao**, nao duas.

| Frame | Resolucao | Fragment consumer | Attachment D24: minimo / maximo | Imagem amostrada: zeros / pixels |
|---|---|---|---|---|
| 712 | 1280x720 | `9f178ae97683fd4e` | 0.9954119322 / 0.9980682730 | 921600 / 921600 |
| 2002 | 1920x1080 | `86d5a3f915a6795f` | 0.9951542613 / 1 | 2073600 / 2073600 |
| 2894 | 1536x864 | `86d5a3f915a6795f` | 0.9951546785 / 1 | 1327104 / 1327104 |

Todos os attachment planes tem geometria; os sampled planes sao inteiramente
zero. Nao ha NaN ou profundidade fora de 0..1. Os bits altos indefinidos da
copia X8_D24 foram ignorados corretamente. O primeiro par mostra o exterior;
os dois seguintes mostram a geometria da casa do telefone. Este ZIP ja cobre
as duas cenas: nao pedir os mesmos logs/shaders/mapas anteriores outra vez.

O attachment estava em `54c980000`; a imagem amostrada, em `5504a0000`.
`producer_relationship` continua `unproven`: capturar a mesma dimensao no
mesmo draw nao estabelece sozinho que a primeira imagem produziu a segunda.
O resultado fundamenta a investigacao das copias, sem provar que toda
diferenca entre dois planes distintos e um erro.

O log confirma revisao `5711117`, tradutor nativo ScarletNX, extensao de
profundidade solicitada/suportada/habilitada e os ports anteriores ON.
Captura de efeitos ON, shaders/sombras OFF, GPU DETALHADA. O analisador de FPS
recusa essa sessao armada para comparacoes. Nao foi calculado ganho de FPS.
Write-watch continua limitado por `/proc/self/pagemap` EACCES; isso nao e uma
nova falta de headers nem motivo para retirar verificacoes.

## Lacuna localizada no codigo fixado

ScarletNX `34853eeae5af132e320adbb0193f13344085bf89` ja possui:

- staging, copias entre imagens, conversoes de upload, swizzle na GPU,
  ownership de memoria e sincronizacao de produtores/consumidores;
- `surface.c:depth_copies_raw`, que exporta D32F/D16 sem conversao;
- `surface.c:vk_rt_overlay`, que sobrepoe resultados recentes do GPU sobre
  buffers usados nas transferencias;
- `dma.c:stage_range` e `blit.c:stage_range`, que reutilizam essa sobreposicao.

Porem, `flush_bytes` exclui D24S8 empacotado; `rt_pending_over` tambem exclui
qualquer superficie sem `flush_bytes`. Assim, uma imagem D24 desenhada pode
ficar ausente dos bytes fornecidos a uma transferencia de memoria. Os bytes
antigos podem continuar zero, mesmo com geometria real no alvo Vulkan.
Um teste do codigo de qualificacao original reproduz exatamente essa exclusao.

Esta e uma lacuna de exportacao demonstrada no codigo, compativel com os
pixels recebidos. A identificacao do pacote especifico do jogo que liga os
dois enderecos ainda depende do resultado ON no aparelho. Nao alterar blend,
brilho, shaders candidatos ou FSWZADD para mascarar a entrada zerada.

## Implementacao e limites

`tools/patch_scarletnx_zelda_d24_pack.py` aplica depois da captura de efeitos e
restaura antes dela. A nova opcao de execucao e `SNX_VK_D24_PACK=1`.

Para alvos qualificados, copia os aspectos depth e stencil para regioes
separadas do scratch existente; o shader interno `texconv` reempacota os bits
em outra regiao, sem sobreposicao de descritores. Reutiliza o swizzle existente
para bloco linear ou a copia de linhas para pitch linear. Os caminhos atuais
de overlay, merge, ownership, geracoes e visibilidade continuam responsaveis
por entregar os bytes ao consumidor correto.

Os layouts ZT sao:

- `0x14` Z24S8: `(depth24 << 8) | stencil8`;
- `0x16` S8Z24: `depth24 | (stencil8 << 24)`.

As identificacoes constam nos [headers oficiais da NVIDIA](https://github.com/NVIDIA/open-gpu-doc/blob/master/classes/3d/clb197.h).
O caminho de upload ja existente no ScarletNX fornece a conversao inversa.
Nao ha passagem por float, aproximacao ou descarte do stencil.

Escopo deliberado: host D24_UNORM_S8_UINT, bpp4, sem escala, um mip, uma
camada, sem volume. Linear exige pitch compacto. Bloco linear exige largura
multipla de quatro pixels e offset alinhado a 16 bytes, pois o kernel
existente move runs completos de 16 bytes. Casos fora do escopo conservam a
politica anterior. As tres resolucoes capturadas atendem a restricao de largura.
Verifica capacidade de alocacao, ranges de storage e limites de dispatch.

As barreiras ordenam reutilizacao do scratch, image-to-buffer, compute e o
consumidor seguinte. O gravador novo nao chama wait/submit. Uma leitura CPU
que agora receba dados antes indisponiveis pode usar os waits **ja exigidos**
pelo caminho original: `recorder_extra_waits=0` nao promete custo total zero.
Copiar depth/stencil e reempacotar custa trabalho e largura de banda; esta e
uma correcao de precisao, sem promessa de aumentar FPS.

Os dois modos tem constantes unicas no SPIR-V. Antes de habilitar a opcao,
o runtime verifica o modulo interno realmente embutido; um shader gerado
antigo/invalido deixa a opcao inativa e registra aviso. CMake/Ninja/glslang
regeneram apenas o shader interno afetado pelas dependencias existentes.
Nao se apagam caches nem se regeneram os blocos AOT do jogo.

Telemetria em janelas existentes:

- `SNX_D24_PACK_META_V1`: solicitado, shader suportado e habilitado;
- `SNX_D24_PACK_STATE_V1`: ate oito alvos exportados por janela;
- `SNX_D24_PACK_V1`: exportacoes, pixels logicos convertidos e falhas.

`pixels` nao representa bytes fisicos de DRAM ou melhoria de FPS. O analisador
exige uma linha completa por janela e rejeita mudanca de modo na sessao.

## Verificacao concluida no host

- 65 testes da auditoria, zero skips com glslangValidator/spirv-val reais;
  toda a pilha aplica duas vezes e restaura exatamente as fontes originais.
- Corpo GLSL real: todos os 16777216 valores de profundidade em cada layout,
  **33554432 casos**, bits altos indefinidos, stencil, pitches, guards,
  preenchimento e roundtrip pelo upload anterior.
- Gravador/qualificacao: OFF, modulo antigo, baseline sem bytes D24, layouts,
  preenchimento de memoria, ordem de barreiras, limites e falhas de alocacao,
  conversao e swizzle. ASan/UBSan passaram. LeakSanitizer nao pode inspecionar
  `/proc` neste host; somente a varredura de leaks foi desativada na repeticao.
- SPIR-V Vulkan1.1 compilado e validado; unidades completas `surface.c`,
  `texconv.c`, `renderer.c`, sintaxe shell/Python e parsing Java verificados.
- Suite anterior `tests/glsl/texconv_glsl.cpp` executada contra o GLSL
  modificado: conversoes anteriores continuam identicas as referencias CPU.
- Componente Vulkan real em **llvmpipe LLVM15, driver de software do host**:
  **23965272 pixels**, dois layouts ZT, linear e bloco linear com bh0/1/4;
  aspectos de imagens D24S8 reais, gravador e funcoes TC/swizzle/barreiras
  extraidos do codigo de producao. Todos os bytes e padding comparados.
  Modulo antigo/invalido rejeitado. Os waits do fixture servem ao readback
  do teste e nao sao parte do gravador de producao.

Isso nao e um teste na Adreno, um APK Android validado, nem prova de que a
nevoa/luz voltou no jogo. O comportamento visual e o custo continuam pendentes.

Teste de componente reproduzivel num host com dependencias Vulkan instaladas:

```bash
python3 tools/run_zelda_d24_vulkan_test.py --source /caminho/ScarletNX
```

Aceita `--vulkan-include`, `--glslang`, `--spirv-val`, `--cc` e `--loader-arg`
para dependencias em outras pastas. Selecionar ICD com `VK_ICD_FILENAMES` se
necessario. Nao exige ROM, shaders capturados ou Android. Em Termux o APK e
o teste principal; nao instalar um driver de software para jogar.

## Comandos e comparacao no RedMagic

```bash
set -e
cd "$HOME/LASRecomp-Android"
git switch experimental/zelda-links-awakening-ryujinx-nativeaot
git pull --ff-only origin experimental/zelda-links-awakening-ryujinx-nativeaot
SCARLETNX_BUILD_JOBS=2 bash ./compilar-zelda-copias-profundidade-termux.sh
```

Saida: `Download/ZeldaRecomp/Zelda-SNX-COPIAS-PROFUNDIDADE.apk`.
O APK anterior de efeitos e preservado uma vez em
`Zelda-SNX-EFEITOS-ANTES-COPIAS.apk`. Os builders existentes reutilizam os
artefatos/caches e validam os assets e marcadores da biblioteca desta revisao.

| Opcao | Uso normal / comparacao visual | Captura para confirmar os pixels |
|---|---|---|
| Preservar faixa de profundidade | ON | ON |
| Corrigir copias da profundidade D24 | ON (OFF so no ensaio de referencia) | ON |
| Ports anteriores de desempenho | Mesmos estados ja usados | Mesmos estados |
| Stable60 | Mesmo estado em ambos os ensaios | Mesmo estado |
| Ryujinx Vulkan automatico | DESLIGADO | DESLIGADO |
| Registrar FPS no log | LEVE | LEVE |
| Capturar shaders / sombras | OFF | OFF |
| Capturar profundidade de luz/nevoa | OFF | ON, tres pares |

A opcao nova aparece apenas no perfil com `Zelda-D24Copies.txt` e comeca ON
se ainda nao houver preferencia salva. Sair do processo e reiniciar depois
de alternar OFF/ON. Guardar a referencia. Se houver regressao, colocar apenas
a nova opcao OFF, mantendo a faixa de profundidade ON, e reiniciar.

Primeiro conferir a mesma vista da casa do telefone e o exterior com nevoa.
Para confirmar a entrada dos shaders, uma unica sessao com captura de efeitos
ON, cerca de 60 segundos entre essas cenas, pode gerar o novo ZIP de efeitos.
O log deve mostrar `shader_supported=1`, `enabled=1`, `packed>0`,
`failures=0`. O novo sampled plane com geometria apoiaria a ligacao real desta
transferencia com o defeito; igualdade pixel a pixel entre attachment atual
e copia amostrada nao e obrigatoria, pois podem vir de momentos diferentes.

Se `packed=0`, nao declarar sucesso: verificar formato/escala/geracao/layout
e estabelecer a linhagem DMA/2D. Se `shader_supported=0`, investigar a geracao
incremental do shader interno sem apagar caches. Se a copia continuar zero
mesmo com exportacoes, rastrear enderecos, ordem/aliases e o consumidor real.
Se a profundidade normalizar e luz/nevoa ainda faltarem, analisar os proximos
inputs/uniformes e os pixels de cor da composicao. Nao alterar blend global.

Somente depois, capturas OFF e processos novos para OFF/ON LEVE de 90 s,
mesmo save/camera/rota/resolucao/cache quente/ventilacao/refresh. Exportar os
dois logs; comparar janelas completas depois do aquecimento. Render, fila do
guest e apresentacao enfileirada sao fluxos distintos; nenhum mede scan-out.

**Falta:** validar a copia/luz/nevoa no aparelho, checar sombras residuais e
blur localizado, medir o custo desta correcao, depois retomar hashing sob
EACCES, transfers/pass breaks e frame pacing. Manter os ports aprovados.
