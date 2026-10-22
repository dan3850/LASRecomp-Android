# Ryujinx nativo -> Vulkan ScarletNX: primeiro fallback visual real

Branch: `experimental/ryujinx-runtime-nativeaot`.

## O que mudou desde o teste anterior

- O log Castlevania-SNX-boot (4).txt confirmou que cinco shaders Maxwell foram traduzidos pelo Ryujinx no processo do jogo, sem exceções, porém como diagnóstico apenas. O ScarletNX continuava ignorando milhares de draws porque o SPIR-V não chegava ao Vulkan.
- Agora existe `ScarletAdapter.cs`: adaptador universal (não baseado em hashes de jogos) com saída C ABI `snx_ryu_translate_scarlet_v1`, metadados de CBs, texturas TIC/TSC, máscaras de entrada e saída.
- O adaptador reescreve descritores SPIR-V Ryujinx para o conjunto ScarletNX: uniform CB -> slot real 0..17 e texturas 2D combinadas -> bindings 34..97, todos no set 1 para fragment. Remove o `support_buffer` somente quando reconhece integralmente o uso de render scale que já foi auditado no projeto offline.
- O patch Vulkan em `pipeline.c` agora CHAMA este export quando o ScarletNX rejeita um shader e tenta entregar o módulo adaptado ao `vkCreateShaderModule`. Somente estados de fragmento validados são aceitos; se a biblioteca for antiga, o shader não se adaptar ou o driver recusar capacidades, continua o fallback normal do ScarletNX.
- Tudo continua opt-in, exclusivamente neste branch de Castlevania. O build Mario estável não é alterado.

## O que está comprovado e o que ainda precisa do aparelho

- Compilação C# -> ELF ARM64 com o export novo: **APROVADA no GitHub Actions** (run 39782638761). Biblioteca: libRyujinxShaderNative.so (9.359.512 bytes).
- As cinco traduções Maxwell -> SPIR-V **sem adaptação Vulkan** tinham sido aprovadas no aparelho (5/5).
- **Ainda NÃO foi testado neste chat** o adapter novo no RedMagic, nem o resultado visual após ligar o Vulkan. Não afirmar que os problemas gráficos já foram corrigidos.
- O script de Termux confere, para cada shader previamente capturado, que o SPIR-V adaptado pelo Ryujinx NativeAOT bate byte a byte com o resultado independente do nosso adaptador Python. Se falhar, INTERROMPE antes da build da APK e não toca no AOT.

## Como testar

1. Baixar `ryujinx-android-arm64-vulkan-adapter.zip` da conversa para a pasta Download (NÃO descompactar).
2. Executar:

    cd "$HOME/LASRecomp-Android" || exit 1
    git pull --ff-only origin experimental/ryujinx-runtime-nativeaot
    bash compilar-castlevania-ryujinx-nativo-termux.sh

3. O script verifica símbolo `snx_ryu_translate_scarlet_v1`, extrai a biblioteca nova de modo seguro, roda os dois testes NativeAOT com os shaders já disponíveis (não precisa novos arquivos), depois compila ScarletNX incrementalmente, usa AOT Castlevania existente, monta e assina a APK:

    /storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-RYUJINX-NATIVO-TESTE.apk

4. Instalar APK, abrir launcher, deixar `Ryujinx Vulkan automatico (experimental)` LIGADO, iniciar Castlevania e salvar log. Procurar `RYUJINX_NATIVE_VULKAN: shader adapted automatically`, `RYUJINX_NATIVE_VULKAN: fallback` e `draws, N skipped`.

## Limites e segurança

- Nenhum shader precisa de cadastramento ou pacote `.snxrbr`. Os cinco shaders são somente vetores de teste para comparação antes da instalação; dentro do jogo o tradutor atende códigos Maxwell novos até o limite de 256 traduções por sessão.
- Atualmente somente shaders de fragmento com texturas 2D combinadas, CBs simples e características suportadas são adaptados. Se forem necessárias storage images, SSBOs, render targets inteiros ou outras extensões, o adaptador recusa, em vez de inventar um binding.
- Os descritores Vulkan, a compatibilidade entre estágios e os resultados visuais REAIS ainda precisam ser validados no dispositivo. O código não promete correção automática de todas as texturas.
- Manter a APK estável anterior. Não dar `clean`, não apagar cache global, não regenerar o game AOT de 603 MB.

## Licenças

Ryujinx.Graphics.Shader e componentes vendorizados nxnative: MIT; ScarletNX GPL-3.0-or-later. Distribuição pública de derivados GPL exige conformidade com as respectivas licenças.
