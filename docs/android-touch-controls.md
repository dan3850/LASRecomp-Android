# Controles de toque Android — layout inspirado no Ryujinx Neo

## Referência e licença

Referência visual e funcional: [Ryujinx Neo (versão Android)](https://github.com/Sunshinin11/Ryujinx_Neo), em especial `src/KenjinxAndroid/app/src/main/java/org/kenjinx/android/GameController2.kt`.

O projeto Ryujinx Neo disponibiliza sua implementação sob a licença MIT, copyright Kenji-NX Team and Contributors. A cópia do texto da licença é mantida em `licenses/Ryujinx_Neo_Android_MIT.txt` e incluída em `assets/licenses/Ryujinx_Neo_Android_MIT.txt` no APK.

O LASRecomp não incorporou a biblioteca externa RadialGamePad nem componentes Kotlin/Compose do Neo. O layout foi implementado diretamente em `GameTouchControls.java` com Android Canvas/MotionEvent e integra os controles existentes via SDL3 e JNI.

## Controles implementados

- Analógico esquerdo: movimento contínuo com raio limitado, zona morta central de 10%, atualiza os eixos X/Y do `nn::hid` de Nintendo Switch. Ao tirar o dedo, volta exatamente ao centro.
- Analógico direito: eixo X/Y independente, com as mesmas regras; pode ser usado simultaneamente com o esquerdo.
- D-Pad dedicado: envia teclas de seta, **não** WASD e **não** o analógico esquerdo. O jogo pode opcionalmente fazer D-Pad mover Link quando o ajuste `dpad_move` estiver ativo; isso já era comportamento do motor e não foi alterado.
- A/B/X/Y, L/R, ZL/ZR, +/- preservados com seus atalhos SDL existentes.
- L3/R3 separados, enviados pelas teclas F e NumPad 0, conforme os bindings padrão do LASRecomp.
- Multitoque: cada dedo mantém seu próprio botão ou analógico; dois dedos não podem roubar o mesmo analógico; soltar/cancelar o toque, perder a janela ou trocar tamanho desativa o estado retido.

## Integração nativa

O Java chama `GameTouchControls.nativeSetTouchAxes(float,float,float,float)`, exportado pela `libmain.so` já carregada pelo SDL. Essa função resolve `lasrecomp_touch_axes` na `liblasrecomp_runtime.so` *depois* que o runtime existe, sem bloquear inicialização.

`runtime/hle/input.c` guarda os quatro eixos em inteiros atômicos 16-bit-equivalentes e os mistura com gamepad/teclado no momento de `GetNpadState`, ignorando-os quando os menus capturam input. O eixo Y do Canvas (para baixo) é invertido para corresponder ao HID (para cima).

A `liblasgame.so` privada, fontes do Zelda, Vulkan, áudio e temporização da simulação não precisam ser alterados.

## Testes

```sh
python3 tests/test_android_neo_touch.py
clang -std=c11 -O2 -Wall -Wextra -Werror tests/test_android_touch_axis.c -lm -o "$PREFIX/tmp/test_android_touch_axis"
"$PREFIX/tmp/test_android_touch_axis"
```

Esses testes validam a ligação entre os arquivos e a normalização numérica, **não** substituem compilar o APK ou conferir as teclas e eixos no aparelho Android real.
