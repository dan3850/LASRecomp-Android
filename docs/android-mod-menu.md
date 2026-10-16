# Menu Mods Android: primeira compatibilidade de codigo

O menu **MODS** importa o `.pchtxt` do Stable 60fps v2 (theboy181) para
Link's Awakening v1.0.0. Tambem permite colar o codigo. Confere o Build ID
completo e aceita somente os dois NOPs de `main+0x01019608` e `main+0x01019628`.
Outros patches, IPS, ZIP, mods RomFS e cheats externos ainda nao sao aceitos
por esse menu. Nenhum mod fica marcado como compativel por apenas ser importado.

## Preparacao unica

Atualize, compile o APK assinado e prepare a biblioteca privada compativel:

```sh
cd ~/LASRecomp-Android &&
test "$(git branch --show-current)" = "android/external-game-folder" &&
git pull --ff-only origin android/external-game-folder &&
bash ./compilar-lasrecomp-pasta-externa.sh &&
python3 tools/apply-stable60-mod.py --menu-compatible
```

1. Instale o **APK novo** gerado em `Download/LASRecomp`. Ele exporta o hook
   nativo e inclui o menu. A biblioteca preparada exige esse runtime atualizado.
2. No aplicativo, use **TESTE: IMPORTAR MINHA LIBLASGAME.SO** e selecione
   `Download/LASRecomp/Mods-menu/liblasgame.so`. O importador verifica o
   carregamento, dependencias e ABI da copia temporaria antes de substituir a
   biblioteca instalada. Uma falha preserva a anterior.
3. Feche completamente e reabra o aplicativo. Em **MODS**, importe o `.pchtxt`
   ou cole o codigo do mod enviado. Ative **Ativar na proxima inicializacao**.
4. Reinicie o aplicativo. A partir dessa preparacao, ativar/desativar esse mod
   pelo menu nao exige gerar outra biblioteca.

O mod comeca desativado. A biblioteca preparada contem tanto as instrucoes
originais quanto os NOPs; o hook seleciona a variante nos dois pontos.
Nao substitua a biblioteca de `Mods-menu` pela de `Stable60-v2`: a segunda e o
mod fixo anterior, sem ativacao reversivel pelo menu.

O helper preserva o NSO, os fontes C, os objetos e a biblioteca originais.
Reutiliza os objetos completos e compila apenas os arquivos afetados e a
identificacao de compatibilidade. Arquivos privados novos ficam na subpasta
`build/private-android-lasgame-termux/stable60-menu` do workspace do jogador.

### Se a importacao falhou com `cannot locate symbol "g_fnprof"`

O motor dos APKs anteriores era aberto com `RTLD_GLOBAL`, mas nao continha
a flag ELF `DF_1_GLOBAL`. O Bionic usa essa flag para incluir uma biblioteca
no grupo global de relocacao. Assim, o importador separado nao conseguia
resolver os simbolos do motor ao carregar o codigo do jogo. Referencia:
[grupo global de relocacao do Bionic](https://android.googlesource.com/platform/bionic/+/refs/heads/main/linker/linker_namespaces.cpp#124).

Os dois caminhos de compilacao do motor agora usam `-Wl,-z,global` e conferem
a flag e os exports reais `g_fnprof`, `fnprof_hit` e `rt_mod_nop` antes de
empacotar. Nao sao criadas copias privadas desses simbolos dentro do jogo.

Atualize e compile o APK pelo comando acima, instale-o por cima da mesma
instalacao, feche completamente e reabra. Importe novamente o mesmo
`Download/LASRecomp/Mods-menu/liblasgame.so`. Esta correcao exige atualizar
o **APK**, sem regenerar o NSO, o codigo C ou a biblioteca privada ja preparada.
O APK assinado fica em `Download/LASRecomp/LASRecomp-pasta-externa-<commit>-signed.apk`.
A tentativa recusada preservou a biblioteca que ja estava instalada.

## Integracao e diferencas para o Eden

Referencia examinada: mirror publico do Eden, commit
`d8c6c59b679867d2595fdc0953df033475e23380`:

- [AddonsFragment.kt](https://github.com/eden-emulator/mirror/blob/d8c6c59b679867d2595fdc0953df033475e23380/src/android/app/src/main/java/org/yuzu/yuzu_emu/fragments/AddonsFragment.kt): importacao Android de pastas de complementos.
- [AddonViewModel.kt](https://github.com/eden-emulator/mirror/blob/d8c6c59b679867d2595fdc0953df033475e23380/src/android/app/src/main/java/org/yuzu/yuzu_emu/model/AddonViewModel.kt): lista e persistencia dos complementos habilitados/desabilitados.
- [ips_layer.cpp](https://github.com/eden-emulator/mirror/blob/d8c6c59b679867d2595fdc0953df033475e23380/src/core/file_sys/ips_layer.cpp): interpretacao de IPS/PCHTXT.
- [nso.cpp](https://github.com/eden-emulator/mirror/blob/d8c6c59b679867d2595fdc0953df033475e23380/src/core/loader/nso.cpp): aplicacao do patch antes da execucao do ARM64.

A adaptacao e uma implementacao propria em Java/C, sem copiar codigo GPL do
Eden ou trazer seu nucleo de emulacao. Compartilha o formato PCHTXT e o fluxo
de importacao/selecao. No LASRecomp, modificar os bytes ARM64 em memoria nao
muda o C ja compilado. Por isso, esta versao usa duas variantes explicitas,
selecionadas por `rt_mod_nop()` na biblioteca privada preparada.

O hook le a selecao de `files/mods/stable60-v2.enabled` uma vez por boot e usa
um valor atomico nos proximos acessos. Somente esses dois PCs podem retornar
NOP. O menu verifica o export `lasgame_mod_menu_v1` e a ABI antes de liberar
a ativacao; bibliotecas antigas continuam funcionando, mas nao liberam esse
controle. Modulos nao preparados nunca chamam o novo hook.

O quadro **ULTIMA SESSAO REGISTRADA**, dentro de MODS, identifica a biblioteca
realmente aberta pelo motor: original, preparada para o menu ou mod fixo.
Separa a selecao carregada da confirmacao de **NOP executado** em cada um dos
dois pontos. Apenas marcar a caixa nao e uma confirmacao de execucao. Se o
jogo ainda nao passou por esses pontos, o quadro informa que esta aguardando.
O resultado e preservado apos um fechamento e entra no ZIP em `mods/status.txt`.
Trocar a selecao da proxima inicializacao nao altera o registro da ultima sessao.
O caminho repetido do hook nao grava arquivos nem relê a selecao.

Os enderecos do PCHTXT sao convertidos a partir dos offsets com cabecalho NSO:
`offset + offset_shift - 0x100`. Assim, o arquivo original com
`@flag offset_shift 0x100` seleciona exatamente os dois PCs esperados.

## Validacao e limites

- `tests/test_stable60_mod.py`: gerador real e C executado no host, alternando
  original/NOP/original, preservacao de LR/flags e relink da biblioteca preparada
  com o hook real; nenhum original e substituido.
- `tests/test_mod_menu.py` e `Stable60PatchTest.java`: validacao do arquivo,
  compatibilidade, importacao atomica, ativacao/desativacao e leitura pelo C
  do mesmo arquivo gravado pelo Java; erros preservam a importacao anterior.
  Verificam tambem biblioteca sem suporte, mod fixo, selecao carregada,
  confirmacao separada dos dois NOPs, ausencia de escrita repetida e reset.
- `mod_library_test.c`: exercita as funcoes JNI de compatibilidade/validacao
  com handles de linker simulados, verificando biblioteca antiga, ABI errada,
  dependencia ausente, permissoes e arquitetura. Nao executa codigo do jogo.
- `test_android_runtime_link.py`: usa as opcoes dos dois linkadores de producao,
  verifica `DF_1_GLOBAL` no ELF e carrega C sintetico do gerador com o profiler
  e hook reais em processos novos. Confere que ambos compartilham o mesmo
  `g_fnprof`, sem substitutos no codigo do jogo. Falha com os dois scripts
  anteriores. A execucao e no host, sem simular o linker Bionic.
- Compilacao de todos os Java do app com SDL3 contra o Android SDK existente.
- Verificacao de compilacao dos novos caminhos C/JNI no host com `__ANDROID__`.

Esses testes nao executam um APK no Adreno. O jogo, a interface no telefone,
o comportamento ao reiniciar e o ganho real de FPS ainda precisam de teste no
celular. O mod impede a mudanca automatica para 30 FPS; nao aumenta por si so a
capacidade da CPU/GPU nem garante 60 FPS. Renderizacao, fontes, audio e controles
nao foram modificados para implementar este menu.
