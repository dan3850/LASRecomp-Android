# Android: RomFS externa sem imagem intermediária

Branch de desenvolvimento: `android/external-game-folder`.
A branch `android/termux-native-build` não é alterada por este trabalho.

Selecione, pelo botão de importar arquivos do jogo, uma pasta com:

```text
exefs/main
exefs/sdk
exefs/main.npdm
romfs/region_common/...
```

Os arquivos precisam pertencer à cópia do usuário de Link's Awakening v1.0.0.
O build ID continua sendo validado. `liblasgame.so` continua sendo carregada
pela rota privada existente ou pelo APK privado; este trabalho não altera a
recompilação dos executáveis nem fornece arquivos do jogo.

Somente `exefs` é preparado no diretório privado, como antes. A árvore `romfs`
faz parte do armazenamento selecionado pelo usuário. Não é copiada, não é
empacotada no APK e não gera `romfs.bin`. Uma imagem `romfs.bin` existente,
externa ou previamente importada para o armazenamento privado, continua
suportada. Quando a pasta selecionada já contém uma imagem, essa imagem é usada.

## Caminho de leitura

1. `GameDocumentBridge` enumera nomes UTF-8, diretórios, tamanhos e IDs SAF.
   Diretórios vazios são preservados. A permissão persistente de leitura é
   obrigatória; permissão de escrita não é necessária.
2. `GameSDLActivity.getGameRomfsIndex()` entrega somente o manifesto UTF-8 via
   JNI. Mantém o mapa de nomes para URIs para não consultar cada ancestral a
   cada abertura de arquivo. O manifesto é reconstruído a cada montagem.
3. `romfs_virtual.c` reproduz o formato e a ordem do gerador `romfs_build.c`:
   cabeçalho, área de dados em offsets virtuais, alinhamento de 16 bytes,
   tabelas hash e metadados de diretórios/arquivos. Só metadados e mapas ficam
   em memória; o tamanho virtual pode superar 4 GB.
4. O IStorage usa a mesma função de leitura base para imagens e pastas. Uma
   leitura pode atravessar cabeçalho, vários arquivos, alinhamento e tabelas.
   Dados reais vêm de `pread` nos descritores originais fornecidos pelo SAF.
5. Há cache LRU de até 32 descritores, protegido por mutex. Reset fecha todos
   os descritores e libera mapas e tabelas. As camadas do randomizer continuam
   acima da leitura base, inclusive substituição e adição de arquivos.

Falhas de permissão, listagem, tamanho, arquivo ausente, leitura curta e
provedores que não oferecem descritores com acesso aleatório são tratadas
como erro. Não existe fallback que copie os dados nem que gere uma imagem.
Somente os espaços de alinhamento virtuais são preenchidos com zeros.
O IStorage devolve erro para leituras inválidas ou incompletas.

O marcador privado da importação contém o URI da pasta selecionada. Isso
mantém a seleção e os executáveis juntos durante a troca atômica de importação,
mesmo se o processo terminar antes da gravação das preferências. Marcadores
antigos com seleção nas preferências continuam aceitos.

## Compilar no Termux

```bash
bash compilar-lasrecomp-pasta-externa.sh
```

Esse script completo atualiza somente a branch experimental por fast-forward,
usa `compilar-lasrecomp-termux.sh`, preserva os caches existentes e verifica a
assinatura. Para outro checkout, defina `LASRECOMP_PROJECT` com o caminho dele.
Alterações rastreadas locais ou histórico divergente interrompem a atualização
sem apagar trabalho. Backups não rastreados são preservados.

O script gera em `/storage/emulated/0/Download/LASRecomp`:

- `LASRecomp-pasta-externa-<commit>-signed.apk`
- `LASRecomp-fontes-<commit>.zip` (projeto versionado completo, sem jogos/caches)

A chave de teste local persistente é reutilizada. A biblioteca privada do jogo
pode continuar sendo importada no app. Não é necessário recompilar essa
biblioteca para mudar o backend de leitura da RomFS.

## Verificação reproduzível sem arquivos de jogo

Requisitos: Python 3 e Clang compatível com os headers SIMD do runtime
(Clang 19 ou posterior; o Clang do NDK também pode executar o teste no host).

```bash
CC=clang python3 tests/test_romfs_virtual.py
bash -n compilar-lasrecomp-pasta-externa.sh
```

Os 12 testes usam o backend C real e os handlers de produção de fsp-srv e
IStorage. A ponte Android é substituída por descritores de arquivos sintéticos
somente no harness dos testes. Cobrem igualdade byte a byte com o gerador
existente, 1.200 leituras aleatórias, diretórios vazios, Unicode, arquivo
esparso de 5.900.000.123 bytes, offsets acima de 4 GB, cache e concorrência,
limites e overflow, arquivos alterados, permissão negada, pipes, remontagem,
imagens antigas e overlays do randomizer.

A compilação Java é verificada com os headers Android 35 e a integração
oficial SDL 3.2.22. O workflow `Android APK (arm64-v8a)` também executa os
testes e compila o motor completo nesta branch. Consultar o resultado do run:
a configuração do workflow, por si só, não comprova compilação bem-sucedida.

Teste no dispositivo ainda necessário: selecionar a pasta real via SAF,
reabrir o app para confirmar a permissão persistente e iniciar o jogo com a
`liblasgame.so` compatível. Testes sintéticos não comprovam o boot do Zelda,
a compatibilidade de todos os provedores SAF nem o desempenho durante o jogo.
