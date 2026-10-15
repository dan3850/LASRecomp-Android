# LASRecomp Android — fase 1 (Termux ARM64)

Este trabalho é **um primeiro teste de APK Android nativo**, não um port jogável.
O teste abre uma NativeActivity do Android, desenha uma tela de diagnóstico
sem Java e verifica se o **loader** Vulkan do sistema pode ser aberto.
Ele **não** cria um dispositivo Vulkan, não compila o LASRecomp e não executa
arquivos do jogo. Não é necessário ter jogos para este teste.

## Requisitos no próprio Android (Termux arm64)

Use o Termux nativo no telefone, fora de proot/chroot. Instale:

```sh
pkg update
pkg install git clang aapt2 zip zipalign apksigner openjdk-21 android-sdk
```

A versão do SDK Platform deve ter `android.jar` em
`$ANDROID_HOME/platforms/android-XX/android.jar`. Normalmente o SDK do
Termux fica em `$PREFIX/opt/android-sdk`:

```sh
export ANDROID_HOME="$PREFIX/opt/android-sdk"
# Se ainda não houver uma plataforma SDK instalada:
sdkmanager "platforms;android-35"
```

Se você já possui `android.jar` de uma instalação existente, basta
definir `ANDROID_JAR=/caminho/para/android.jar` no Termux.

## Compilação

```sh
cd ~
git clone -b android/phase1-termux-bootstrap \
  https://github.com/dan3850/LASRecomp-Android.git
cd LASRecomp-Android
bash tools/build-android-termux.sh
```

A saída esperada é
`build/android-bootstrap/LASRecomp-Android-phase1.apk`.
O script reutiliza a pasta de saída, sem executar `make clean`, e
gera uma chave local de **debug** persistente
(`~/.lasrecomp-android-debug.keystore`) na primeira execução.
Não use essa chave para uma versão publicada.

Instale o APK no telefone (via gerenciador de arquivos/instalador autorizado).
A tela deve exibir **LASRECOMP ANDROID**, **ARM64 BOOTSTRAP** e o resultado da
sondagem **VULKAN LOADER FOUND/MISSING**. Consulte os logs:

```sh
logcat -d -s LASRecompAndroid:I AndroidRuntime:E
```

O Termux pode ter acesso limitado ao `logcat` dependendo da versão do
Android e das permissões; a tela serve como verificação primária.

## Limites e próximas etapas

- O Android usa **Bionic**, não glibc; o `Makefile` Linux atual não gera
  um APK e `runtime/platform/linux.c` não é uma camada Android.
- A recompilação do jogo no desktop gera a biblioteca dinâmica `lasgame.so`
  durante a configuração inicial. Isso exigirá uma estratégia própria para
  Android (geração/compilação e carregamento em diretório interno autorizado).
- O guest memory mapping e o carregamento dinâmico devem ser validados
  com o processo Android, páginas de 16 KiB e as restrições de memória.
- Vulkan do aplicativo e SDL3, FFmpeg, entrada, áudio e importação de
  arquivos virão **depois** de confirmada a NativeActivity.

O teste inclui uma biblioteca ELF alinhada para até 16 KiB de páginas com
`-Wl,-z,max-page-size=16384`; isso por si só não garante que o runtime
do jogo seja compatível com dispositivos de 16 KiB.

Nada do jogo da Nintendo é distribuído neste repositório.
