# Castlevania / Ryujinx ABI 2 no Termux

## Teste do cache JIT na reabertura

Comparacao dos logs enviados: o log 12, com defeitos visuais relatados, carrega 66 unidades do `.jitcache` (15 KiB de codigo JIT ao final, nenhuma compilacao). O log 13, com graficos corretos relatados, carrega zero unidades e compila 66 funcoes / 388 instrucoes (49 KiB, 0,24 s de compilacao). Ambos registram a mesma identidade NativeAOT `36276fc4...bc69`. Existem outras diferencas: pacote `.graphics` versus pacote Termux, revisao `95b7a977` versus `2301a16`, toolchain de runtime clang 19 versus 21, e duracao/cena da sessao. A comparacao **nao prova** que o cache JIT cause os defeitos.

O novo patch Termux testa essa hipotese no pacote existente. Quando o titulo e `0100BA4026E94000` e `SNX_RYUJINX_NATIVE_PROBE=1`, usa o contrato `SnxJitConfig.cache_path=NULL`: o servico nao abre nem grava o cache de objetos compilados. Tambem nao consulta as dicas de partidas anteriores para aquecimento. O JIT continua compilando as funcoes necessarias durante a execucao; o AOT do jogo nao e recompilado. Os arquivos `.jitcache`, dicas, saves e configuracoes existentes nao sao apagados. Com Ryujinx desligado e em outros titulos, a politica original continua em vigor.

O runtime imprime `SNX_JIT_COLD_START_V1: persistent units and warm hints bypassed; files preserved`. A verificacao da APK assinada agora exige esse marcador alem da revisao Git e da identidade C#. O cache de fontes e restaurado ao sair do build, incluindo `guest_jit.c`. A biblioteca NativeAOT ja baixada continua valida, pois nenhuma fonte C# foi alterada.

Instale por cima da APK Termux anterior, sem limpar os dados, mantenha Ryujinx ligado e compare a mesma cena em tres aberturas completas. Um resultado com zero unidades JIT carregadas e graficos ainda ruins refuta a suficiencia desse desvio de cache. O resultado visual e as reaberturas ainda precisam de validacao no RedMagic. Nenhuma compilacao Actions e necessaria para esta alteracao.

Esta entrada usa a instalacao ARM64 de Termux, NDK r28c, SDK/Java, modulo AOT ABI 12 e cache ScarletNX dos builds anteriores. Nao e um instalador do ambiente do zero. Nao usa Termux proot e nao recompila o AOT do jogo. O ScarletNX original, as dependencias nativas e o modulo do jogo continuam sendo exigidos pelos scripts existentes.

O runtime Vulkan e a APK sao compilados no celular. A biblioteca C# NativeAOT Android ARM64 continua sendo publicada pelo GitHub Actions: o compilador .NET Android usado no CI nao e instalado por este script.

1. Baixe explicitamente o ZIP do artefato **ryujinx-v2-95b7a977ecdeddcdac1e7676f1bb1fbab85633ac**, em https://github.com/dan3850/LASRecomp-Android/actions/runs/39806670484/artifacts/12437533041 . Salve-o em Downloads como `ryujinx-v2.zip`. Esse ZIP contem a biblioteca NativeAOT; o ZIP de APK e outro artefato.
2. Na copia existente do repositorio, use a branch `experimental/ryujinx-runtime-nativeaot` e execute `git pull --ff-only`.
3. Execute:

```bash
termux-setup-storage
bash compilar-castlevania-ryujinx-v2-termux.sh /storage/emulated/0/Download/ryujinx-v2.zip
```

O script recomputa a identidade a partir das fontes C# locais e do nxnative fixado. Carrega a biblioteca ARM64, exige a exportacao ABI 2 e compara a identidade real. Nao aceita uma biblioteca antiga com apenas os mesmos nomes de funcoes. Se as fontes C# forem alteradas novamente, um novo artefato Actions correspondente sera necessario.

O teste sintetico do tradutor executa tambem `spirv-val` quando disponivel (`pkg install spirv-tools`). Sem essa ferramenta, o teste SPIR-V e explicitamente marcado como nao executado; identidade e integridade da APK continuam obrigatorias.

O script reutiliza o cache de compilacao e restaura as alteracoes temporarias da ABI 2 nas fontes compartilhadas ao sair. Nao execute outros builds que utilizem esse mesmo cache simultaneamente. Uma copia datada da APK experimental anterior e preservada. Ao terminar, verifica SHA-256 da biblioteca dentro da APK assinada e exige no runtime a identidade C#, revisao Git atual e marcador ABI 2. So entao produz:

`/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-RYUJINX-V2-TESTE.apk`

Essa APK usa o pacote experimental dos scripts Termux existentes, diferente do pacote `.graphics` do CI. No launcher, ative **Ryujinx Vulkan automatico (experimental)**. A compilacao no Termux e a renderizacao final ainda precisam ser verificadas no aparelho; os testes de integridade nao comprovam que os defeitos graficos desapareceram.

## Reopening regression: session-local driver pipeline cache

A device report found correct graphics after clearing app data, but corruption
when closing and reopening. ABI 2 already bypassed `.vkshaders` prewarm, while
`vk_pipeline_init` still loaded `vk_pipelines.bin` before that bypass.

The experimental ABI 2 runtime now also skips reading and writing the persistent
Vulkan pipeline cache when `SNX_RYUJINX_NATIVE_PROBE=1`. The Vulkan cache remains
available in memory within a session. Existing files, game saves, imported keys,
modules and preferences are preserved. The original backend's persistence is
unchanged. Pipeline compilation may recur on each launch. This is a targeted
cache-isolation workaround; the device report alone does not establish the root
cause or prove a driver defect.

Local validation: the patch applies twice to pinned ScarletNX `34853ee`;
`tests/test_ryujinx_v2_reopen.py` compiles and executes the injected guards in a
C harness across three ABI 2 sessions with existing cache data, followed by a
normal-backend session. No Android APK was compiled locally or in Actions for
this change. The NativeAOT adapter inputs are unchanged: reuse the existing
`ryujinx-v2-95b7a977ecdeddcdac1e7676f1bb1fbab85633ac.zip`.

Device acceptance: update and build with the existing Termux ABI 2 script;
keep app data intact and confirm the launcher has Ryujinx Vulkan enabled. Open
the same scene, close the application, reopen it, and repeat twice. If corruption
returns, save the bad-session log before clearing any data. The new diagnostic
is `RYUJINX_NATIVE_V2: persistent pipeline cache bypassed; files preserved`.
