# Correção de GMEM e atualização de atlas R8

Base auditada: `9c6389ced2d38639cdfe841ff7757c0c7e1ffbcf`, na branch
`android/external-game-folder`.

## Falhas encontradas e mudanças

1. **LDG/STG fora do descritor.** O tradutor verificava o endereço contra os
   3,25 GB do heap, mas o descritor de fallback tinha somente 4 KB. Sem importação,
   um acesso fora do mapa podia ler/escrever fora desse buffer. Agora o shader
   exige uma importação real para usar o caminho direto, verifica o comprimento
   do descritor e o tamanho completo da operação. A busca de bytes/halfwords usa
   o endereço da palavra que os contém: o último byte de um range de 4 bytes não
   cai erroneamente no fallback.
2. **Compute com escrita sem memória real no Android.** `gfast_prepare()`
   retornava sem preencher a tabela quando a importação não existia. O caminho
   portátil agora fornece snapshots próprios, com armazenamento Vulkan válido,
   para leituras e escritas. A tabela inclui os 16 storage buffers, 18 uniform
   buffers e constantes do shader que estão no heap. Sobreposições são fundidas.
   O limite artificial de 1 MiB foi substituído pelo limite real do descritor do
   dispositivo; não há publicação silenciosa de uma tabela parcialmente truncada.
3. **Vida útil e visibilidade de resultados.** Cada dispatch que escreve possui
   sua própria alocação. Uma barreira compute → host, conclusão da timeline e
   invalidação VMA precedem a cópia de volta. Somente bytes diferentes do snapshot
   inicial são aplicados ao heap. Fences devolvem resultados ao jogo antes de
   retornar; leituras dependentes de buffers, índices, vértices, uniformes e
   texturas resolvem a dependência antes de tirar um novo snapshot. Não há flush
   bloqueante incondicional após cada dispatch, como nos experimentos revertidos.
4. **Atlas atualizado dentro do mesmo frame.** `backend_pool_written()` ignorava
   os flushes NVN. Tanto o memo de views quanto `upload_texture()` podiam manter
   a versão anterior do atlas mesmo depois de uma atualização explícita. Agora
   uma geração atômica invalida esses atalhos para texturas lineares. Uploads
   repetidos são ordenados. Não se alteraram a fonte, os swizzles ou os pixels.
5. **Heap importado em outros dispositivos.** Draws gráficos usam a importação
   diretamente, sem reutilizar a tabela de scratch de um compute anterior.
   O caminho original de compute com importação continua disponível.

## Fontes, texturas e apresentação

No ZIP `LASRecomp-grafico-20261016-060426.zip`, a fonte está carregada e há
atualizações do atlas linear R8 1024×2048. O swizzle Vulkan `ONE, ONE, ONE, R`
produz RGB branco e cobertura no alfa; não há fundamento para substituí-lo.
O ZIP concatena sessões anteriores: isso não constitui uma captura visual do
HEAD auditado nem identifica, sozinho, qual shader pertence a cada texto.

Foram examinados o carregamento TrueType em `runtime/hle/pl.c`, os caminhos de
formatos, upload, views e samplers em `textures.c`, os descritores e draw/dispatch
em `exec.c` e o contrato GLSL/reflexão SPIR-V em `shaders.c`. O Metal original
liga o heap real a LDG/STG. A solução portátil mantém os dados dos ranges NVN
nesses acessos, sem exigir `VK_EXT_external_memory_host`.

Não foram modificados apresentação, resolução, FPS, temporização, controles ou
lógica do jogo. Endereços fora dos ranges NVN conhecidos continuam sem uma cópia
real no caminho portátil: o acesso é protegido, mas esse caso não implementa
memória virtual GPU irrestrita. Escritas GMEM em estágios gráficos sem importação
também não recebem o novo writeback compute; não apareceram nos registros usados.

## Validação reproduzível

```sh
python3 tests/test_vulkan_gmem.py
```

Dependências: clang/clang++, headers SDL3, Vulkan e VMA, loader/ICD Vulkan,
`glslangValidator` e `spirv-val`. Os caminhos adicionais são configuráveis por
`VULKAN_TEST_CFLAGS`, `VULKAN_TEST_LDFLAGS` e `VK_ICD_FILENAMES`.

Os testes executam o código real de alocação/writeback do executor e os caminhos
reais de upload/view/memo/sampler R8, usando dados sintéticos e shaders Maxwell
sintéticos, sem arquivos do jogo. No ambiente Linux com Lavapipe passaram:

- 13 casos de memória: LDG de 8/16/32/64/128 bits, extensão de sinal, último
  byte/halfword, aliases, limites, LDG via uniform buffer, STG de 8/16/128 bits,
  snapshots independentes e aplicação seletiva depois da conclusão.
- Upload e amostragem de atlas R8 com alfa correto, incluindo alteração explícita
  no mesmo frame. Repetir esse teste com `textures.c` de `9c6389c` e uma geração
  constante, correspondente ao antigo flush vazio, falha na verificação do alfa
  atualizado. A implementação corrigida passa.
- Compilação e validação SPIR-V dos 14 shaders de teste.
- Planejamento de ranges e cópia seletiva com AddressSanitizer/UBSan
  (`detect_leaks=0`, porque o ambiente bloqueia a inspeção de threads do LSan).
- Comparação de 10.000 programas Maxwell contra `9c6389c`: 8.021 traduções Metal
  idênticas; 1.979 programas rejeitados por ambas as versões; zero diferenças.
- Compilação dos módulos alterados em C no host, incluindo os condicionais
  `__ANDROID__`/Volk. Isso não é uma compilação ARM64 com NDK nem um APK.

O teste R8 verifica dados que chegam ao sampler; não rasteriza o jogo completo.
Não há jogo/ROM, aparelho Android ou Adreno 840 disponível neste ambiente. Não
foram comprovados aqui os textos, iluminação, composição final ou desempenho no
celular. A validação restante é recompilar com o script Termux existente e
comparar a mesma tela de menu/diálogo, a casa inicial e a área externa. O cache
SPIR-V depende do código-fonte GLSL e naturalmente distingue os shaders alterados;
não é necessário apagar os caches ou executar um clean.

## Desempenho e fechamento: ZIP de 16/10/2026, 10:25:43

O usuário confirmou melhora da iluminação e de outros elementos após o caminho
portátil. A última sessão desse ZIP cai de 30,1 para 13,7 FPS, com até 530,4 MiB
de uploads a cada aproximadamente dois segundos. Termina em SIGSEGV com endereço
zero; não há registro de device loss Vulkan nessa sessão. O fechamento também
aparece em sessões anteriores à correção portátil. Isso não identifica sua causa.

As mudanças seguintes preservam a cobertura GMEM e o writeback:

- Snapshots somente de leitura idênticos são compartilhados dentro da mesma
  submissão. Nova submissão, flush CPU, atualização inline ou writeback modificado
  invalidam o cache. São 128 entradas de metadados, sem manter cópias extras.
- Alocações compute concluídas e já copiadas de volta podem ser reutilizadas.
  Dispatches pendentes continuam com buffers distintos. O pool mantém no máximo
  oito buffers e 16 MiB de capacidade Vulkan, mais o mesmo tamanho de baselines
  CPU; alocações maiores são descartadas após a conclusão. O reboot esvazia o pool.
- A comparação do resultado pula blocos iguais com `memcmp`, mantendo precisão de
  bytes nos blocos alterados. Ranges sem mudanças não invalidam atlas e snapshots.
- A compilação Termux passa a registrar dependências de headers. Antes, mudar
  `vk.h` podia combinar objetos compilados com layouts diferentes de `TexBackend`.
  Os objetos nativos antigos sem depfile são recompilados uma vez. Esse script
  não recompila nem apaga a biblioteca privada de código do jogo.

Os 13 casos Maxwell e a amostragem R8 continuam passando em Lavapipe. O teste
adicional executa 501 leituras idênticas de 1 MiB e verifica exatamente 1 MiB de
uploads; verifica também invalidação CPU/inline/por submissão, preservação dos
snapshots anteriores, buffers pendentes distintos, reutilização após conclusão
e ausência de invalidação por dispatch sem mudanças. Os limites de quantidade e
capacidade do pool também são exercitados. O helper passou com
AddressSanitizer/UBSan. Três testes compilam objetos C reais para verificar
dependências, mudança de layout, cache sem depfile e preservação após erro.

O relatório antigo chamava tanto PC quanto LR de `f_70013c21e0`: os dois nomes
apontavam ao mesmo buffer temporário, sobrescrito pela consulta de LR. O nome do
PC era incorreto, embora o endereço e o offset numéricos fossem preservados.
Agora os nomes são independentes e o offset de LR também é impresso. Um teste
reproduz a colisão e verifica os dois símbolos. **Essa correção identifica melhor
o fechamento; não corrige por si só o acesso nulo do código do jogo.**

A biblioteca privada e as funções geradas correspondentes não estão neste
checkout nem no ZIP. Para recuperar o trecho relevante usando o ZIP existente,
sem jogar novamente, recompilar o jogo ou enviar sua biblioteca inteira:

```sh
python3 ~/LASRecomp-Android/tools/extract-android-crash.py \
  ~/storage/downloads/LASRecomp-grafico-20261016-102543.zip \
  ~/lasrecomp-android-gen \
  --output ~/storage/downloads/LASRecomp-crash-code.txt
```

Use o diretório que contém a geração e a `liblasgame.so` não stripada **do mesmo
teste**. `--library` permite indicar outro caminho. Nos relatórios antigos a
ferramenta limita os candidatos usando os endereços PC/LR, offset do PC e tamanho
do chamador no ELF; não presume que o nome antigo do PC esteja certo. O relatório
gerado inclui apenas os trechos selecionados e suas chamadas diretas, e deve ficar
fora do Git. Seis testes verificam seleção e extração, inclusive um ELF real com
ZIP sintético e rejeição de crash mais recente sem símbolos. A recuperação de FPS, a ausência de regressão
visual e o encerramento do jogo ainda precisam ser avaliados no aparelho.
