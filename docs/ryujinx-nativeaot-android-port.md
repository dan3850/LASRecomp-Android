# Ryujinx no Android: tradutor nativo real (Etapa 1)

Branch: experimental/ryujinx-runtime-nativeaot

Objetivo: portar o código real do tradutor Ryujinx para Android ARM64. A abordagem anterior, que exigia pacotes .snxrbr individuais para cinco ou seis shaders, está DESCONTINUADA neste novo caminho.

## Código implementado

- RyujinxShaderNative.csproj: referencia os projetos originais Ryujinx.Graphics.Shader e Ryujinx.Common do nxnative e publica libRyujinxShaderNative.so por .NET NativeAOT no RID linux-bionic-arm64.
- prepare_source.py: cria uma cópia local temporária de Program.cs (somente a classe SwshXlate vira partial). NÃO edita o nxnative nem o ScarletNX. Evita atualizar timestamps se o código não mudou.
- BridgeExports.cs: chama Translator.CreateContext(... TargetLanguage.Spirv, TargetApi.Vulkan ...) REAL. Exporta snx_ryu_api_version, snx_ryu_translate_v1 e snx_ryu_free_v1 como funções nativas C. Recebe bytes Maxwell e contexto; retorna SPIR-V e reflexão dinâmica de CBs, SSBOs, texturas e imagens.
- test_native.py: por ctypes, chama a biblioteca no Android e traduz todos os shaders encontrados nos ZIPs locais, sem lista fixa de hashes; verifica SPIR-V, metadata e opcionalmente spirv-val.
- provar-ryujinx-nativo-termux.sh: executa build/prova local, não modifica APK, AOT, ScarletNX nem cache Vulkan.

## Teste no Termux

    cd "$HOME/LASRecomp-Android" || exit 1
    git status --short
    git fetch origin
    git switch experimental/ryujinx-runtime-nativeaot 2>/dev/null || git switch --track origin/experimental/ryujinx-runtime-nativeaot
    git pull --ff-only origin experimental/ryujinx-runtime-nativeaot
    python3 -m unittest discover -s tests -p test_ryujinx_nativeaot_prepare.py
    bash provar-ryujinx-nativo-termux.sh

Pré-requisitos: checkout existente em ~/.cache/lasrecomp-ryujinx-probe/nxnative; dotnet SDK 10; clang e python3. Não se faz clean. A primeira publicação AOT pode precisar baixar um runtime pack do NuGet.

Saída de sucesso esperada (não confirmada até teste no aparelho): 'RESULTADO: 5/5 shaders translated by NativeAOT'. Log: ~/ryujinx-nativeaot/build.log. A biblioteca compilada fica em ~/.cache/lasrecomp-ryujinx-nativeaot/publish/libRyujinxShaderNative.so.

## Etapas seguintes (AINDA NÃO IMPLEMENTADAS)

1. Provar o build NativeAOT e a chamada nativa real no aparelho. Se não compilar, corrigir o erro concreto antes de mexer no ScarletNX.
2. Fornecer contexto gráfico verdadeiro (tipo/formato de textura, CBUF1, atributos e saídas) ao tradutor. O teste atual usa consultas-padrão apenas para validar execução, NÃO para renderizar.
3. Adaptar SPIR-V/reflection ao esquema Vulkan/descritores do ScarletNX. SPIR-V validado isoladamente NÃO significa renderização correta.
4. Integrar .so ao APK experimental com fallback por shader para Maxwell arbitrário, cache por código+estado e sincronização. Sem .snxrbr e sem hashes fixos.
5. Comparar a renderização com Ryujinx ON/OFF e preservar o build já funcional.

## Licenças

Os projetos do tradutor Ryujinx vendorizados pelo nxnative usam MIT. O ScarletNX é GPL-3.0-or-later; distribuir o aplicativo com código ScarletNX exige atenção às obrigações específicas da licença. O MIT do tradutor não muda essa condição.

Esta é uma entrega de infraestrutura real, NÃO uma alegação de port integrado ao Vulkan ou APK pronto.
