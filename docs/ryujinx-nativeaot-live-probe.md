# Ryujinx NativeAOT — etapa 2: chamada ao vivo dentro do ScarletNX

**Branch isolada:** `experimental/ryujinx-runtime-nativeaot`

## Evidências já comprovadas

- O RedMagic executou a biblioteca real `libRyujinxShaderNative.so` por ABI C no Termux e traduziu 5/5 shaders de fragmento Maxwell, com 0 erros, sem `.snxrbr` e sem shaders pré-gerados.
- O GitHub Actions compilou a mesma biblioteca de 8.977.104 bytes para Android ARM64; o C ABI `snx_ryu_translate_v1` existe no ELF.
- Isso prova a tradução nativa, mas NÃO prova compatibilidade dos layouts Vulkan durante uma partida. É necessário adaptar os descritores e E/S dos shaders.

## Código desta rodada

- `patch_scarletnx_live_probe.py` injeta no `pipeline.c` do ScarletNX PINNED uma chamada a `snx_rn_live_probe()` somente quando a tradução nativa de um fragment shader falhou.
- Essa chamada `dlopen` carrega a biblioteca NativeAOT empacotada no diretório privado de bibliotecas do APK e invoca o C# Ryujinx diretamente. Sem ZIPs, sem lista de hashes fixos.
- O resultado SPIR-V/reflexão é apenas diagnosticado, sem substituir o módulo Vulkan; o resultado e os erros do ScarletNX são preservados. Até 32 traduções por execução para limitar o custo experimental.
- Tela Castlevania: botão `Tradutor Ryujinx NativeAOT (diagnostico): LIGADO/DESLIGADO`, desligado por padrão. O antigo controle de importar `.snxrbr` foi retirado.
- O exportador dos logs ganhou seção `TRADUTOR RYUJINX NATIVO AO VIVO` mesmo quando o log total tiver milhões de linhas.
- `compilar-mario-snx-runtime-termux.sh` empacota `libRyujinxShaderNative.so` ao lado do ScarletNX, verifica arquitetura/símbolos e confirma SHA-256 do binário no APK assinado. Não altera o módulo do jogo.
- `compilar-castlevania-shader-termux.sh` aplica o patch no checkout ScarletNX temporário e o reverte na saída; reutiliza caches.
- `compilar-castlevania-ryujinx-nativo-termux.sh` é o novo ponto de entrada de build. Não constrói os 603 MB do AOT, não pede dump nem arquivo .snxrbr.

## Próximo teste no celular

Pré-requisito: a biblioteca ARM64 já está em `~/ryujinx-nativeaot/libRyujinxShaderNative.so` (confirmado pelo teste 5/5).

    cd "$HOME/LASRecomp-Android" || exit 1
    git pull --ff-only origin experimental/ryujinx-runtime-nativeaot
    bash compilar-castlevania-ryujinx-nativo-termux.sh

Após o build, instalar `Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-RYUJINX-NATIVO-TESTE.apk`, abrir o launcher e ativar `Tradutor Ryujinx NativeAOT (diagnostico)`. Jogar até a cena que falhava e usar `Salvar log`. Procurar:

    RYUJINX_NATIVE_PROBE: real C# translator loaded in game process (ABI 1)
    RYUJINX_NATIVE_PROBE: translated NEW fragment Maxwell (...), diagnostic only

Se aparecer `dlopen failed`, investigar carregamento/namespace; se aparecer `translate failed`, investigar contexto/recursos. Em ambos os casos o caminho de renderização ScarletNX não é alterado.

**AVISO:** esta rodada NÃO corrige gráficos. A tradução já funciona no Termux; este teste comprova sua chamada real dentro do pipeline do jogo. Não prometer melhora de pixels nesta fase.

## Segurança e estado

- Ramo Mario estável não tocado.
- APK anterior preservada como `Castlevania-SNX-Runtime-ANTES-RYU-NATIVO.apk` e novo arquivo experimental separado.
- NativeAOT desligado por padrão; o import antigo de `.snxrbr` não é usado.
- Nenhum shader, jogo, XCI ou prod.keys enviado ao GitHub.

## Passo seguinte depois do log

Passar do probe diagnóstico para o uso efetivo do SPIR-V, com mapeamento dinâmico dos descritores (`SNX_VKB_CB`, `SNX_VKB_TEX`, imagens e SSBOs), estado real das texturas, shader IO e validação do módulo Vulkan. Fallback e cache seguro obrigatórios. Não substituir a saída Vulkan antes dessas validações.
