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
