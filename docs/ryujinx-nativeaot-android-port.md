# Tradutor Ryujinx Android ARM64 — port nativo (Etapa 1)

Branch: experimental/ryujinx-runtime-nativeaot

## Resultado REAL obtido

- O .NET 10.0.112 no Termux compilou todos os projetos C#, mas não conseguiu publicá-los em NativeAOT: o SDK procura runtime.linux-bionic-arm64.Microsoft.DotNet.ILCompiler, pacote não publicado para o host Android. Não tentar contornar com referência NuGet inventada.
- O GitHub Actions agora executa a publicação NativeAOT linux-bionic-arm64 em Linux x64 com Android NDK instalado. A compilação foi confirmada no run https://github.com/dan3850/LASRecomp-Android/actions/runs/39771803764 (sucesso).
- Biblioteca saída: libRyujinxShaderNative.so (ELF ARM64 compartilhada). Símbolos confirmados: snx_ryu_api_version, snx_ryu_translate_v1, snx_ryu_free_v1. ELF ET_DYN, machine AArch64; dependências: libc.so, libdl.so, libm.so.
- Artefato aprovado: ryujinx-android-arm64-nativeaot.zip, contendo .so, cabeçalho de ABI, README e SHA256SUMS. Nenhum shader privado ou dump está nesse pacote.
- Verificação no Android/Termux com ctypes ainda é a PRÓXIMA PROVA; não alegamos integração com ScarletNX Vulkan ou APK pronto.

## Teste de tradução de shaders diretamente pela biblioteca NO REDMAGIC

Baixe o ZIP do artefato do run 39771803764, ou o arquivo enviado nesta conversa, e salve em Download com o nome ryujinx-android-arm64-nativeaot.zip. Não extraia.

    cd "$HOME/LASRecomp-Android" || exit 1
    git pull --ff-only origin experimental/ryujinx-runtime-nativeaot
    bash testar-ryujinx-nativo-termux.sh

Alternativa compatível: bash provar-ryujinx-nativo-termux.sh (agora chama exatamente o teste; não tenta a publicação NativeAOT impossível no Termux).

O script extrai com validação SHA-256 e cabeçalho ELF ARM64 para $HOME/ryujinx-nativeaot/libRyujinxShaderNative.so, carrega-a pelo ctypes do Termux e traduz TODO shader presente em Castlevania-shaders-SNXS*.zip via o código Ryujinx C# NATIVO, sem hashes fixos. Os shaders originais servem apenas como arquivos de TESTE e NÃO são embutidos na biblioteca. Resultados locais: $HOME/ryujinx-nativeaot/shaders; log: $HOME/ryujinx-nativeaot/test.log.

Se a biblioteca falhar ao carregar, o próximo diagnóstico é uma dependência/símbolo ELF ou restrição de linker Bionic. Se carregar, mas o tradutor retornar erro, verificar o contexto real de recursos ou diferenças do NativeAOT. Não modificar arquivos do jogo nem mascarar falhas com shaders previamente convertidos.

## Status das próximas etapas

1. Publicação do tradutor Ryujinx real como .so Android ARM64: CONCLUÍDA no GitHub; chamada no telefone: AINDA NÃO TESTADA.
2. Obter tipos/formatos de recursos e tabelas CBUF1 do ScarletNX para os pedidos de shader do Ryujinx: PENDENTE.
3. Adaptar SPIR-V e reflection para layouts Vulkan do ScarletNX sem defaults incorretos: PENDENTE.
4. Vincular a .so no APK experimental, tradução automática de shaders Maxwell por código+estado, cache e fallback nativo: PENDENTE.
5. Comparar gráficos com o Ryujinx ligado/desligado preservando o APK original: PENDENTE.

## Licenças

O tradutor original Ryujinx vendido pelo nxnative tem licença MIT. O ScarletNX continua GPL-3.0-or-later; o uso do tradutor MIT não anula possíveis obrigações ao distribuir binários derivados do ScarletNX.

Não usar novamente as estratégias de pacotes .snxrbr individuais nesta branch. Não executar Gradle clean/AOT desnecessariamente.
