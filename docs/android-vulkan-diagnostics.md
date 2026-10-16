# Vulkan: texturas, memória e captura no Android

Implementação experimental em `android/external-game-folder`.

## Alterações no renderizador

- Formatos BC1–BC7 sem suporte de amostragem no driver são descomprimidos pela CPU antes do upload. A conversão preserva o espaço sRGB, os canais normalizados com sinal de BC4/BC5 e o HDR em RGBA16F de BC6H. Mips, camadas, profundidade e blocos parciais são tratados.
- Texturas lineares escritas pela CPU, incluindo atlas R8 usados pelos textos, são verificadas integralmente desde a primeira atualização. Escritas esparsas não dependem da amostragem de um hash parcial.
- Memória mapeada do staging é descarregada antes da submissão; buffers de leitura são invalidados depois da espera da GPU. As operações são dispensadas internamente pelo VMA quando a memória é coerente.
- Samplers respeitam o suporte e o limite de anisotropia. Extensões opcionais de borda e mirror clamp só são usadas com seus recursos necessários.
- A captura conserva o tamanho e o formato originais do readback mesmo se a apresentação provocar uma recriação da swapchain.

## Capturar o defeito

1. Abra a cena com o defeito e toque em **CAPTURAR LOG**, no topo da tela.
2. Aguarde a confirmação e toque em **SALVAR ZIP**.
3. Escolha o destino no seletor de arquivos do Android.

O ZIP contém a captura da saída Vulkan, o relatório de capacidades e contadores, eventos gráficos, até quatro atlas R8 elegíveis lidos separadamente da CPU e da GPU e o início/final do registro do motor. O relatório identifica o commit, GPU, driver, formatos, camadas, hashes e swizzles. A coleta registra até 128 draws entre o pedido e a apresentação; não é um traço completo de todos os comandos do frame.

O botão **SALVAR DIAGNÓSTICO GRÁFICO (ZIP)** na tela inicial também exporta o registro disponível depois de uma falha. A coleta usa apenas os arquivos de diagnóstico do aplicativo; não percorre a pasta SAF do jogo nem inclui ROM, executáveis, biblioteca do jogo ou arquivos de fontes.

Capturar requer esperas e leituras da GPU e pode causar uma pausa breve. As leituras de imagens e o registro de draws só acontecem por solicitação; contadores e eventos repetidos são limitados. A captura da swapchain aceita RGBA8/BGRA8; outro formato gera uma falha explícita com relatório disponível.

## Limites da correção

As mudanças não comprovam a causa dos defeitos no RedMagic. O fallback existente de memória global sem `VK_EXT_external_memory_host` ainda fornece um buffer de zeros: agora cada uso é contado e registrado com estágio e identificador de shader. Substituir esse caminho exige validar quais acessos reais do jogo o utilizam, incluindo escrita e sincronização; esta alteração não afirma implementar esse substituto.

A leitura de volta de uma textura comprimida que foi descomprimida para a GPU exigiria recompressão. Esse caso é detectado e registrado, em vez de copiar pixels descomprimidos para um buffer dimensionado para blocos comprimidos.

`tests/test_bcn_decode.py` verifica pixels conhecidos, canais com sinal/HDR, bordas, duas fatias, tamanhos de buffer e overflow. A compilação Android completa verifica Java/JNI e a ligação ARM64. O boot e os resultados visuais do jogo precisam de validação em aparelho.

O script Termux continua na mesma branch, preserva alterações locais, assinatura e caches, e gera o APK e os fontes. O APK do CI usa um pacote de teste paralelo para preservar a instalação existente.
