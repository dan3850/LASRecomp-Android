# LASRecomp-Android: compilar no Termux (ARM64)

Script **independente** do GBAura e de `tools/build-android-termux.sh`, baseado no commit restaurado `35f268cb`.

## Executar

No Termux normal (fora de PRoot/Ubuntu), instale **apenas o que estiver faltando**:

```sh
pkg install git clang cmake ninja make python openjdk-21 android-sdk aapt2 d8 zip zipalign apksigner patchelf
pkg install python-fonttools
```

Use o SDK Android que já estiver no celular. O script procura `ANDROID_HOME` e depois o SDK do Termux. O SDK precisa conter uma plataforma com `android.jar` e uma pasta NDK com `libc++_shared.so`. O script **não executa o NDK Linux x86-64**.

```sh
cd ~
git clone -b android/termux-native-build https://github.com/dan3850/LASRecomp-Android.git LASRecomp-Android
cd ~/LASRecomp-Android
bash compilar-lasrecomp-termux.sh
```

Para builds posteriores (sem apagar caches e sem `clean`):

```sh
cd ~/LASRecomp-Android
git pull --ff-only
bash compilar-lasrecomp-termux.sh
```

Se a pasta do projeto já existe, use-a (não clone de novo). Para um checkout existente em outra branch, crie uma worktree específica para **não trocar a branch restaurada**:

```sh
cd ~/LASRecomp-Android
git fetch origin android/termux-native-build
git worktree add ~/LASRecomp-Termux origin/android/termux-native-build
cd ~/LASRecomp-Termux
bash compilar-lasrecomp-termux.sh
```

## O que o script faz

- Baixa SDL3, shaderc, FFmpeg, volk e VMA na primeira execução e mantém suas árvores em `~/.cache/lasrecomp-termux`. Os builds CMake, Ninja e objetos próprios são reaproveitados.
- Compila o motor original LASRecomp/ImGui/Vulkan, a ponte SDL e a Activity Java **no Termux ARM64**, sem copiar o código do GBAura.
- Monta o APK, valida bibliotecas ELF ARM64 e dependências, usa `zipalign` e assina com uma chave debug local persistente.
- Não faz `reset`, `clean`, recompilação do Zelda ou upload dos arquivos do jogo.
- Salva log em `build/termux-native/compilacao.log`, APK em `build/termux-native/LASRecomp-Android-Termux.apk` e, se o armazenamento estiver disponível, copia para `Download/LASRecomp`.

Para permitir a cópia à pasta Downloads no Termux, rode `termux-setup-storage` uma única vez e autorize o acesso.

O código recompilado do jogo **não está no repositório**. Se o usuário já possuir `liblasgame.so` ARM64 compilada localmente a partir de seus arquivos, pode indicar `LASRECOMP_GAME_SO=/caminho/privado/liblasgame.so` antes do comando. Não envie essa biblioteca para o GitHub.

## Limitação importante

**O script foi criado e salvo, mas ainda não foi executado em um Termux real.** As dependências SDL3, shaderc e FFmpeg podem exigir ajustes específicos do toolchain Termux para produzir bibliotecas compatíveis com o processo do APK. A verificação ELF e a assinatura não comprovam o boot do jogo. Se falhar, preservar `compilacao.log` e corrigir apenas o ponto de compilação, sem mexer no runtime ou nas fontes do jogo.
