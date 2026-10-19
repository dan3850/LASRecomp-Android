# Super Mario 3D World + Bowser's Fury — extração XCI (Android/Termux)

**Branch:** `android/super-mario-3d-world-port`.

O Yanu original já suporta XCI **via conversão XCI -> NSP** usando 4NXCI,
seguida de `yanu unpack --base` (ou o antigo `yanu-cli`). Esta branch fornece um orquestrador
local para fazer as duas etapas, sem modificar o Yanu, sem baixar conteúdo
do jogo e sem copiar chaves privadas para o repositório.

- Yanu: https://github.com/nozwock/yanu (GPL-2.0).
- Comandos upstream: `yanu convert --kind nsp`, `yanu unpack`.
- O instalador oficial do Yanu para Termux cria o comando **`yanu`**; o nome
  `yanu-cli` foi descontinuado. O script detecta automaticamente ambos.
- Requisitos: `python3`, `yanu` ou `yanu-cli` funcional no Termux, espaço suficiente e
  os próprios arquivos de autorização/chaves locais que seu Yanu já utiliza.
  O repositório **não inclui nem fornece chaves de terceiros**.

## Como usar

Coloque o dump da **sua própria cópia** do jogo em uma pasta acessível ao
Termux; não coloque XCI, NSP, EXEFS, ROMFS ou `prod.keys` no GitHub.

```bash
cd "$HOME/LASRecomp-Android"
python3 tools/extrair_mario_xci.py "/storage/emulated/0/SwitchRoms/Super.xci"
```

O caminho de saída padrão será:
`/storage/emulated/0/SwitchRoms/Super-extraido/`, com
`exefs/main`, `exefs/` e `romfs/`.

Se o XCI gerar **vários NSPs** (por exemplo, base e patch), a ferramenta não
chuta qual é o base. Lista os candidatos e pede nova chamada usando
`--base-nsp NOME_DO_BASE.nsp`.

Os NSPs intermediários são mantidos na pasta `_yanu_converted/`, para
permitir reaproveitar a conversão sem repetir o trabalho nem perder o XCI
original. Use `--delete-intermediate` **somente se desejar** excluir o NSP
intermediário selecionado **depois** de extrair e validar os diretórios.

```bash
python3 tools/extrair_mario_xci.py "/caminho/meu-jogo.xci" --output "/pasta-extraida"
python3 tests/test_mario_xci_unpack.py
```

Os testes utilizam um `yanu-cli` falso e arquivos fictícios, não executam
descriptografia nem distribuem material protegido.

Se o script não encontrar Yanu, verifique qual comando existe antes de
instalar ou baixar qualquer ferramenta novamente:

```bash
command -v yanu || command -v yanu-cli
```

Se você já usa o comando `yanu`, a branch corrigida funciona sem opções extras.
Se o Yanu estiver fora do PATH, utilize `--yanu-cli /caminho/do/executavel`.

## Limitações

- Não suporta diretamente extensões comprimidas `.xcz` ou partes `.xc0`.
- A conversão temporária pode exigir bastante armazenamento livre.
- A extração precisa de um Yanu/4NXCI funcional e de dados/chaves obtidos
  pelo próprio usuário com autorização. Mensagens de falha do Yanu não
  devem ser ignoradas.
- Se uma extração estiver **incompleta**, o script para e não sobrescreve
  os arquivos existentes.
- A validação verifica `exefs/main` e existência de conteúdo em `romfs`,
  **não prova integridade criptográfica nem compatibilidade do jogo**.
- **Extração não equivale a um port.** O motor atual LASRecomp é específico
  para Zelda. Super Mario 3D World + Bowser's Fury exigirá análise própria
  do executável, recompilação específica e implementação dos serviços.
  Nenhum APK jogável de Mario é produzido por esta etapa.

**Não publicar** dump do jogo, módulos recompilados derivados de arquivos
proprietários, arquivos da Nintendo ou chaves no GitHub.
