# Link's Awakening v1.0.0 — Stable 60fps v2

Para importar/colar e ativar/desativar pelo novo menu Android, use a
[biblioteca preparada para o menu Mods](android-mod-menu.md). O procedimento
abaixo continua disponivel para gerar o mod fixo anterior.

Aplicador do mod fornecido pelo usuario, de **theboy181**, para a biblioteca
privada de codigo recompilado do LASRecomp Android. O mod substitui por NOP
as instrucoes de `main+0x01019608` e `main+0x01019628`, exclusivamente no
Build ID `AE16F71E002AF8CB059A9A74C4D90F34BA984892`.

O objetivo do mod e impedir a troca automatica para 30 FPS. Isso **nao garante
60 FPS reais**: CPU, GPU, compilacao de shaders e transferencias de memoria
continuam limitando o desempenho. O ganho e o comportamento em cenas lentas
precisam ser medidos no aparelho. Resolucao, renderer, fontes, audio, controles
e os contadores Vulkan nao sao alterados por este aplicador.

## Aplicar no Termux

Reutiliza `~/lasrecomp-android-gen/build/gamecode`, seus objetos completos em
`build/private-android-lasgame-termux/objects` e a biblioteca original ja
compilada. Nao regenera o jogo inteiro nem recompila os objetos originais.

```sh
cd ~/LASRecomp-Android &&
git fetch origin android/external-game-folder &&
git merge --ff-only FETCH_HEAD &&
python3 tools/apply-stable60-mod.py
```

O aplicador procura primeiro em
`~/lasrecomp-android-gen/extracted/exefs/main` e
`~/lasrecomp-android-gen/exefs/main`. Se nao estiver ali, procura automaticamente
no home do Termux, em Downloads, nos rootfs do proot-distro e no armazenamento
compartilhado. Aceita somente `main`/`main.nso` com cabecalho NSO e Build ID
corretos; ignora caches, pastas do sistema e locais sem acesso. A procura le
apenas cabecalhos e nao extrai ou modifica arquivos. Tambem pode indicar o
arquivo explicitamente:

```sh
python3 tools/apply-stable60-mod.py --nso /caminho/do/jogo/exefs/main
```

Para outro workspace privado, use `--workspace /caminho/lasrecomp-android-gen`.
O aplicador usa a biblioteca e os headers desse workspace, sem atualizar seu
checkout ou instalar dependencias. Em funcoes com jump tables que precisem de
emulacao, usa o Unicorn do ambiente de geracao existente; se faltar, interrompe
com erro, sem modificar os originais.

O resultado fica em:

```text
/storage/emulated/0/Download/LASRecomp/Stable60-v2/liblasgame.so
```

Feche o jogo e importe esse arquivo na opcao **TESTE: IMPORTAR MINHA LIBLASGAME.SO**
da tela inicial do app. A atualizacao do Git ou do APK, sozinha, nao substitui
o codigo privado anteriormente importado. Nao e preciso compilar um APK para
este mod. A verificacao de importacao existente continua conferindo ELF ARM64,
carregamento, ABI e tabelas.

Para desfazer, importe a biblioteca original preservada em
`~/lasrecomp-android-gen/build/private-android-lasgame-termux/liblasgame.so`.
Essas bibliotecas contem codigo derivado do jogo e permanecem privadas.

## Protecoes e validacao

- Confere o Build ID completo antes de preparar arquivos.
- Encontra as funcoes pelos enderecos da tabela original e reproduz seu C com
  o gerador existente. Exige correspondencia exata com as funcoes do jogador;
  codigo diferente ou editado e recusado.
- Reemite somente essas funcoes, substituindo as duas instrucoes por NOPs no
  cache de instrucoes do gerador. Mantem os demais trechos de cada arquivo.
- Grava copias, objetos e biblioteca do mod numa subpasta `stable60-v2`.
  Preserva NSOs, C, objetos e `liblasgame.so` originais, inclusive seus mtimes.
- Reutiliza os outros objetos, mantendo `GAMELIB_ID="dev"` e a ABI existentes.
  Confere os exports e recusa novas dependencias indefinidas ao relinkar.
- Replicacoes reaproveitam tambem os objetos do mod que continuam atuais.

O `offset_shift 0x100` do pchtxt compensa o cabecalho do NSO ao criar IPS;
na imagem em memoria e nos enderecos do C ele nao deve ser somado. Referencia
primaria: [exemplo do IPSwitch](https://github.com/3096/ipswitch/blob/master/example/splat310.pchtxt).

`tests/test_stable60_mod.py` usa NSOs sinteticos nos mesmos offsets, o gerador
real e compilacao/execucao de C no host. Verifica NOPs em chamadas e saltos,
preservacao de LR/flags, dois arquivos separados, descompressao, rejeicao de
versao/C divergentes e relink incremental preservando todos os originais.
O teste de relink usa objetos e bibliotecas do host, substituindo explicitamente
as verificacoes Android; **nao e um teste de APK, Bionic ou Adreno**.

Nao foi possivel executar o Zelda nem verificar o FPS no celular neste ambiente.
Na primeira avaliacao, compare a mesma rota, incluindo saida/entrada da casa,
dialogos e animacoes, observando FPS e velocidade do jogo. Se houver piora,
importe a biblioteca original para voltar ao estado anterior.
