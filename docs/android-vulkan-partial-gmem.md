# GMEM parcialmente dinâmico e dependências de compute

Base: `16dfaa5`, branch `android/external-game-folder`.
Log analisado: `LASRecomp-grafico-20261016-195107.zip`, última sessão.

## Evidência no aparelho

O exterior estabiliza em 30 FPS, ~459 MB de cópias por dois segundos e
`gmem saved 0.0MB`, mesmo sem compilação de shaders ou desenhos pulados.
Na casa há 60 FPS, ~128 MB de cópias e ~225 MB evitados. Os pares de
contadores agora aparecem; intervalos ~13,3 ms no exterior não medem todo
o custo CPU/GPU de entregar um frame. Não houve acesso direto ao aparelho.

O log não permite distinguir snapshots totalmente mutáveis de planos que
mudam de endereço, limites de tamanho ou falta de slots disponíveis. Não
se atribui todo o FPS baixo a uma única causa. O identificador antigo no
arquivo de diagnóstico também impede identificar o APK só por esse campo.

## Mudanças

- Quando uma alocação GMEM de leitura já terminou na GPU, comparar todos os
  bytes com sua cópia CPU, em blocos de até 4 KiB por faixa empacotada.
  Copiar somente os blocos diferentes; manter a verificação integral,
  flush de memória não coerente e proibição de sobrescrever dados em uso.
  Antes, qualquer diferença provocava cópia integral do plano.
- Para leitura CPU dependente de compute, encontrar a última submissão
  que pode escrever na faixa. Se concluída, resolver invalidate/copyback;
  se enviada, esperar só por ela. Enviar o command buffer atual somente
  quando o produtor ainda não foi submetido. Antes, todo overlap chamava
  `renderer_flush`, incluindo comandos posteriores sem relação com a leitura.
- Contabilizar `gmem saved` também para blocos preservados. Os campos
  `bypass-size` e `bypass-capacity` mostram bytes que ficaram fora desse
  cache por limite de tamanho ou slots ocupados/orçamento. Eles não medem
  tráfego físico; ajudam a distinguir por que o exterior não reutiliza dados.

Nenhum shader, efeito, áudio, controle, vsync ou intervalo do jogo alterado.
Nenhuma barreira GPU removida. Limites de memória e elegibilidade mantidos.
Snapshots de escrita continuam separados e protegidos pelo copyback seletivo.

## Testes executados

Clang 20, Vulkan Lavapipe/llvmpipe, `tests/test_vulkan_gmem.py`:

- 60 snapshots de 1 MiB com uma alteração pequena por submissão: 240 KiB
  copiados em vez de 60 MiB. Comparação integral da sombra e do buffer
  mapeado confirma todos os bytes. Esse é um teste sintético, não Zelda.
- Os 13 testes de shader LDG/STG exercitam produtor ainda não submetido,
  produtor submetido e produtor concluído; trabalho posterior permanece
  não submetido e os resultados/bytes CPU vizinhos são preservados.
- Snapshots persistentes, isolamento de buffers em uso e de escrita,
  limites do pool, pares de timestamps e atlas R8: PASS.
- Controles negativos: restaurar só a cópia integral faz falhar a asserção
  de bytes copiados; restaurar só a espera antiga faz falhar a asserção de
  que comandos posteriores não foram submetidos. Fontes corrigidas foram
  restauradas após os testes negativos.

A economia em Adreno, estabilidade visual e FPS no exterior ainda precisam
ser medidos. Nenhum APK foi compilado neste ambiente; usar o script Termux
existente, que atualiza a branch e compila/assina incrementalmente sem clean:

```bash
(
  set -e
  cd "$HOME/LASRecomp-Android"
  if [ "$(git branch --show-current)" != "android/external-game-folder" ]; then
    echo "ERRO: branch diferente; nada foi alterado."
    exit 1
  fi
  bash ./compilar-lasrecomp-pasta-externa.sh
)
```

APK assinado e ZIP de fontes em `/storage/emulated/0/Download/LASRecomp/`.
Não é necessário recompilar a biblioteca privada do jogo para estas mudanças.
