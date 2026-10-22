# Castlevania Belmonts Curse — teste ScarletNX por XCI

Branch **exclusivamente experimental**:
`experimental/castlevania-belmonts-curse`. Base do Mario:
`5a61db3579f38003287b9b7dc15abff9349f8c90`.

## O que o código upstream realmente faz

O ScarletNX fixado em `34853ee` diferencia duas operações:

1. O **driver** abre um dump XCI, prepara e recompila o título.
2. O **runtime** abre `<game>_code.so` via `plat_dl_open`, consulta
   `snx_module` (ABI 12) e só então chama `fs_init`, `loader_load`,
   `kernel_run_main` e o frontend.

O runtime recusa um XCI passado diretamente a `--game=`. Em contrapartida,
`--source=PATH` é uma opção de jogo (`source` no `.ini`) que permite
ao `dump_open` de `src/nx/hle/filesystem/fs.c` mapear o contêiner XCI
para ler **ExeFS e RomFS sem materializar uma segunda cópia**. O loader
confere se os módulos encontrados correspondem ao que foi recompilado.
A leitura exige chaves compatíveis do próprio console do usuário; no
Android de teste ficam em `snx-home/.switch/prod.keys` no armazenamento
interno privado do aplicativo.

O APK antigo do Mario carregava ExeFS extraído e
`SNX_EXTERNAL_ROMFS` para a RomFS externa. Isso **não** prova que o
caminho XCI direto funciona no Android. Este experimento habilita a opção
do upstream sem substituir o fallback do Mario nem editar a branch estável.

## Experimento

O aplicativo **experimental e separado para não sobrescrever o Mario**
usa o mesmo `libscarletnx.so` compilado para Android, dependências
nativas e ciclo SDL3. Ele tem um inicializador de teste e instala
`libcastlevania_snx.so` com o módulo AOT compilado pelo ScarletNX.
O código AOT **não** é recompilado novamente.

No Termux, no checkout que já compilou o Mario:

```bash
cd "$HOME/LASRecomp-Android"
git fetch origin experimental/castlevania-belmonts-curse
git switch experimental/castlevania-belmonts-curse
git pull --ff-only
# Arquivo exportado do ScarletNX para Download:
export CASTLEVANIA_SNX_CODE_SO="/storage/emulated/0/Download/Castlevania-Atualizado/0100BA4026E94000/0100BA4026E94000_code.so"
bash compilar-castlevania-snx-termux.sh
```

O script **não exige a biblioteca privada AOT do Mario nem seu profile**.
O módulo de 603 MB do Castlevania foi preparado pelo ScarletNX e é
empacotado diretamente. O teste reaproveita o runtime ScarletNX corrigido
em `$HOME/scarletnx-romfs-build/libscarletnx.so` e os caches de
dependências do compilador Android. Se o runtime corrigido estiver ausente,
o script interrompe com uma mensagem; não baixa novamente o jogo nem chama
`clean`.
O wrapper confirma ELF ARM64, símbolo `snx_module` e sidecar ABI 12,
quando presente, antes de empacotar. **Não** fornece nem gera jogos,
chaves ou módulos recompilados.

Saída prevista:

`/storage/emulated/0/Download/CastlevaniaRecomp/Castlevania-SNX-Runtime-TESTE.apk`

No aplicativo: selecionar o XCI mesclado, selecionar **seu** `prod.keys`,
aprovar manualmente a leitura da memória interna e iniciar. O runtime
recebe `--game=<app-private>/<id>`, `--source=<XCI selecionado>`,
`--log=2` e `--fullscreen`. Seu `<id>_code.so` é um **symlink** para
a biblioteca ARM64 instalada no diretório nativo do APK. Não grava
executáveis no diretório de dados nem copia o XCI.

Seleção direta exige um documento do volume `primary:`, acessível por
POSIX, e Android 11+ com permissão explícita de gerenciamento de arquivos.
Os logs podem ser salvos usando o botão do teste. **Nunca inclua
`prod.keys` em relatórios públicos.** Este caminho não promete execução
se o contêiner XCI mesclado, as chaves, a ABI ou os serviços do novo jogo
não forem suportados.

## Primeira verificação

1. O AOT passou por `snx_module`/ABI?
2. `SCARLETNX_MAIN_ENTERED` apareceu?
3. O log tem `fs: ExeFS and RomFS read from the dump` (modo direto)?
4. `loader_load()` encontrou `main`, `sdk` e `rtld` esperados?
5. O runtime alcançou `kernel_run_main` e houve quadro apresentado?

Na ausência de leitura do XCI, diagnosticar as chaves, o pacote e o
`source=`; **não** recompilar os 1.152 blocos por tentativa. Se
`loader_load` recusar o conteúdo, conferir o build ID e a atualização
correspondente ao AOT antes de alterar o motor.

## Limites da fase

Ainda não existe menu único multi-jogos nesta branch: o APK isolado
permite validar a integração sem afetar o Mario funcional. Tampouco
há prova de boot do Castlevania até executar no dispositivo. ScarletNX
e suas bibliotecas GPL exigem cumprimento das licenças se distribuídos.

## Primeira rodada de correção gráfica: FSWZADD 0xD7

A cena de gameplay do Castlevania mostra HUD e cenário, mas fragmentos
pretos e geometrias ausentes. O primeiro log exportado contém 19 avisos
"shader not translated": 14 com FSWZADD cuja máscara é 0xD7,
5 com "untracked texture handle". Em 600 quadros:
52.349 draws, 27.182 ignorados. Não há prova de que todos esses
draws sejam de shaders FSWZADD.

Na revisão 34853ee do ScarletNX, o tradutor só aceita quatro máscaras
de FSWZADD. O patch experimental em
tools/patch_scarletnx_fswzadd.py aceita especificamente 0xD7 e gera
SPIR-V para seus dois resultados por lane: y nas lanes 0 e 3 e y-x
nas lanes 1 e 2. A interpretação usa SubgroupLocalInvocationId & 3.
Ela é coerente com a tabela de FSWZADD conhecida no Ryujinx, mas a
ordenação de fragment quads na Adreno ainda requer teste visual.

Para executar a rodada **sem sobrescrever o runtime usado no Mario**:

```bash
cd "$HOME/LASRecomp-Android"
git pull --ff-only origin experimental/castlevania-belmonts-curse
bash compilar-castlevania-shader-termux.sh
```

O wrapper usa o Ninja cache do runtime existente, cria
$HOME/scarletnx-castlevania-shader-build/libscarletnx.so e instala
o AOT Castlevania inalterado no APK experimental. O runtime estável
$HOME/scarletnx-romfs-build/libscarletnx.so permanece inalterado.
Antes da build, o APK anterior é salvo como
Castlevania-SNX-Runtime-ANTES-FSWZADD.apk na pasta CastlevaniaRecomp.
A alteração transitória do fonte cache é revertida ao final.

Comparar uma captura da **mesma cena**, procurando melhora em fragmentos
que antes não eram desenhados. No log novo, conferir se os avisos
FSWZADD desapareceram e se a contagem de draws ignorados diminuiu.
Se o jogo não abrir, enviar o novo log da compilação ou runtime.
Os 5 casos de "untracked texture handle" não são corrigidos nesta rodada.
