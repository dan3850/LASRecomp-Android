# Mario: cobertura estrutural de tabelas ARM64 (modo full)

O APK do teste de Mario conseguiu renderizar imagem, mas continua encerrando
com `FATAL: no function at ...` em entradas internas não presentes no
dispatcher de endereço exato. A saída anterior de
`mario_static_switches.py` encontrou 336 tabelas verificadas, 720 destinos
ainda não registrados e 200 blocos contendo esses destinos no módulo
`main`. Esses números são daquela análise, não representam uma cobertura
garantida em versões posteriores.

## Regra de segurança

`MARIO_VERIFIED_SWITCHES=full` ativa uma varredura *opt-in*, restrita aos
NSOs originais **locais** identificados por Build ID e SHA256, que:

1. Reconhece somente tabelas com instruções ARM64 e bytes originais
   efetivamente verificados; nunca converte simplesmente todo endereço de
   crash em entrada presumida.
2. Planeja os blocos de origem completos, sem dividir uma tabela verificada
   para caber num orçamento pequeno.
3. Verifica `main` **e** `sdk` antes de alterar qualquer fonte gerado.
   `--require-complete` recusa o plano caso ainda falte qualquer destino
   das tabelas reconhecidas.
4. Se os dois planejamentos passarem, consolida as reentradas em **uma
   chamada** de `mario_resume_repair.py`, com transação e recuperação,
   preservando fontes e objetos compilados não afetados.
5. Não habilita os lotes heurísticos anteriores
   (`MARIO_SCENE_BATCH`, `MARIO_NEXT_BATCH`,
   `MARIO_THIRD_BATCH`, `MARIO_AUTO_BATCH`) por padrão no modo `full`.
   Quem precisar testá-los pode ativá-los explicitamente.

Orçamentos padrão do modo `full` **por módulo**: até 256 blocos,
1.048.576 bytes de instruções originais e até 65.536 bytes por bloco. Os
limites aceitos pelo planejador impedem passar de 1 MiB por módulo; isso
**não** é uma estimativa de memória consumida pelo APK ou do tamanho do C
gerado. A falha do orçamento interrompe o procedimento sem recompilar.
Nunca execute `clean` apenas por usar este modo.

## Auditoria somente leitura

Em Termux, após `git pull --ff-only`:

```bash
cd "$HOME/LASRecomp-Mario-Teste" || exit 1
python3 tests/test_mario_static_switches.py || exit 1
for module in main sdk; do
    python3 tools/mario_static_switches.py \
      --game "/storage/emulated/0/SwitchRoms/Super-extraido" \
      --output "$PWD/build/private-mario-full-test" \
      --module "$module" --all-verified --require-complete \
      --max-blocks 256 --budget-bytes 1048576 --max-block-bytes 65536 \
      >/dev/null || exit 1
done
```

O relatório `verified-global` informa `selected_owners`,
`selected_bytes`, `pending_case_targets` e
`unselected_case_targets`. Exigir `unselected_case_targets=0` garante
somente a **cobertura das tabelas que o analisador reconheceu**, não de
todos os saltos indiretos possíveis do executável.

## Um único reparo incremental + build

```bash
MARIO_VERIFIED_SWITCHES=full \
MARIO_STATIC_SWITCH_BLOCK_BYTES=65536 \
bash ./compilar-mario-boot-termux.sh
```

O script já inclui os testes e os dois planejamentos. É propositalmente
mais pesado que reparar um único bloco, mas não regenera o jogo inteiro.
Preserve uma cópia do APK que já renderizou antes de instalá-lo.

## Limitações importantes

* Uma tabela indireta que não corresponda aos padrões comprovados continua
  fora da cobertura, como pode ocorrer com sequências sem guarda local.
* Um endereço pode estar registrado e ainda assim falhar por semântica ARM64,
  corrupção de memória, HLE/NVN ou driver de vídeo.
* A versão ainda precisa ser testada individualmente em **Super Mario 3D
  World** e **Bowser's Fury**.
* O modo `full` não é um interpretador ARM64 dinâmico, nem habilita execução
  nativa de código Switch no Android.
* Nunca incluir NSOs, ROMs, a biblioteca privada compilada, código gerado
  ou segredos na branch GitHub.
