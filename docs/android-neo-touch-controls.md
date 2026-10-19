# Controles Android: layout Neo / Nintendo Switch

Implementação experimental da interface de toque baseada no comportamento dos controles
Android de [Ryujinx Neo / KenjinxAndroid](https://github.com/Sunshinin11/Ryujinx_Neo),
especialmente `GameController2.kt` no branch `neo-v2-nce2`.

O projeto de referência usa componentes Kotlin/Compose e RadialGamePad. Aqui foi
criado um controle Java Canvas integrado ao SDL3 existente, sem adicionar
Compose/RadialGamePad, copiar assets, ou modificar o Vulkan. A atribuição
MIT da referência encontra-se em `third_party/kenjinx-android/LICENSE.txt`.

## Mapeamento (Switch / nn::hid)

| Comando visual | Mecanismo | Saída |
|---|---|---|
| Analógico esquerdo | JNI -> libmain -> runtime/hle/input.c | eixo `leftX,leftY`, -32767..32767 |
| Analógico direito | JNI -> libmain -> runtime/hle/input.c | eixo `rightX,rightY`, -32767..32767 |
| D-Pad | SDL Android keyboard | Up/Down/Left/Right independentes |
| L3 / R3 | SDL Android keyboard | F / Numpad 0 (defaults do motor) |
| A/B/X/Y | SDL Android keyboard | K/J/L/I |
| L/R/ZL/ZR | SDL Android keyboard | Q/E/1/3 |
| +/- | SDL Android keyboard | Enter/Backspace |

Em ambos os analógicos, o deslocamento do dedo controla a magnitude real
independentemente do D-Pad. Os pares X/Y são publicados atomicamente no
motor de entrada; não é feita simulação por quatro botões. Os dedos são
acompanhados separadamente para permitir multitoque. A soltura do dedo,
`ACTION_CANCEL`, pausa e destruição da Activity zeram os eixos e liberam
os botões pressionados. L3/R3 são botões separados (um toque ou duplo toque
no analógico não os ativa acidentalmente).

A superfície Vulkan, seu timing e a biblioteca privada `liblasgame.so`
permanecem inalterados. A versão do motor APK precisa combinar com a
interface: o JNI só publica o setter depois de o runtime estar carregado.

## Verificação

No Termux, na branch que contém a implementação:

```sh
mkdir -p "$PREFIX/tmp"
clang -std=c11 -O2 -Wall -Wextra -Werror tests/test_touch_axes.c -o "$PREFIX/tmp/test_touch_axes"
"$PREFIX/tmp/test_touch_axes"
```

Resultado esperado: `TEST_TOUCH_AXES_PASS`.

O teste verifica amplitude, sinal, separação dos analógicos, entrada inválida
e retorno ao centro. Compilar o APK valida o Java e a resolução de símbolos
do código nativo. Somente um teste real no telefone verifica multitoque,
JNI do SDL, interface visual, foco e input do Zelda.

### Teste manual no Zelda

1. Andar lentamente com o analógico esquerdo e depois empurrar até a borda.
2. Mover o direito enquanto mantém o esquerdo; devem ser independentes.
3. Pressionar D-Pad durante o analógico; seus sinais devem permanecer separados.
4. Pressionar L3, R3, A/B/X/Y, L/R/ZL/ZR, + e − separadamente.
5. Pausar/retomar o app com os analógicos pressionados; eles devem recentrar.

O jogo pode não atribuir uma ação visível a cada botão do controle Switch.
Isso não significa que o botão deixe de ser enviado ao serviço `nn::hid`.
