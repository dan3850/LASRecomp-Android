# Mario: experimento com o recompilador completo

Branch: `android/mario-full-recompiler-test`.
Base preservada: `6b10ac6188ac6c5862108b9dfef20b0106f23de2`, da branch
`android/super-mario-3d-world-port`.

Esta etapa reutiliza `tools/gen.py` e `tools/lifter.py` para gerar os módulos
inteiros `main` e `sdk`. Não usa o limite de 128 bytes do gerador experimental
de funções leaf. O perfil Zelda continua sendo o padrão dos comandos existentes.

O perfil `--profile mario` mantém as instruções originais do executável:
patches por endereço, variantes do randomizer e hooks Stable 60fps do Zelda
ficam restritos ao perfil Zelda. `--expect-build-id` recusa uma versão de
entrada diferente antes de criar a saída. O Build ID fixa a versão fornecida;
nesta etapa não há uma lista de Build IDs do Mario previamente homologados.

## Executar no Termux ARM64

Na cópia de trabalho da branch de teste:

```bash
bash compilar-mario-full-test-termux.sh \
  /storage/emulated/0/SwitchRoms/Super-extraido
```

Reutiliza Python, Capstone, LZ4, clang e llvm-nm já instalados.
Unicorn é opcional. Sem ele, saltos indiretos conservam todos os destinos locais
da função em um dispatcher, incluindo endereços carregados da memória; destinos
fora da função seguem para o dispatcher do runtime. Apenas o teste que executa
o ARM64 original no Unicorn fica marcado como `skipped`. A presença ou ausência
do Unicorn faz parte da configuração do cache de geração.
Não baixa novamente o jogo nem depende de NDK, proot, Gradle ou GitHub Actions.
`MARIO_JOBS=2` é o padrão; pode ser ajustado entre 1 e 8.

Saídas relativas à cópia de trabalho:

| Arquivo | Conteúdo |
|---|---|
| `build/private-mario-full-test/libmario_test.so` | Biblioteca privada com os módulos recompilados |
| `build/private-mario-full-test/build-report.json` | Build IDs, hashes, bases, contagens e símbolos pendentes |
| `build/private-mario-full-test/compilacao.log` | Saída da geração e compilação |
| `build/private-mario-full-test/generated/main/generation.json` | Manifesto do `main`, incluindo instruções não suportadas |
| `build/private-mario-full-test/generated/sdk/generation.json` | Manifesto do `sdk` |

Geração e objetos são reaproveitados por conteúdo e configuração do compilador.
Arquivos interrompidos usam `.partial`; o resultado anterior só é substituído
depois de uma etapa bem-sucedida. Nenhum comando `clean` é executado.
Somente os arquivos presentes no manifesto entram na linkagem.

O SDK é posicionado após o `main`, alinhado a 64 KiB, se a imagem do Mario
ultrapassar os 64 MiB usados pelo Zelda. Essas bases são registradas no relatório
e deverão ser respeitadas pelo futuro carregador Mario.

## O que o resultado comprova

O teste verifica a arquitetura ELF e o export `mario_test_tables`, e recusa
funções recompiladas `f_*` que continuem sem definição na linkagem.
Funções `rt_*`, o dispatcher e o profiler ainda dependem do runtime hospedeiro.
Instruções não suportadas permanecem como traps explícitas, com amostras no
relatório; não são substituídas por NOPs ou retornos de sucesso.

Os testes usam NSOs sintéticos: chamadas entre funções e módulos, callback
indireto, loop para trás, função maior que 128 bytes, memória e SIMD. O C nativo
é comparado ao ARM64 original executado pelo Unicorn. Há também compilação dos
fontes com SIMD inline para o alvo Android ARM64 e verificação do cache incremental.

**Esta biblioteca não é um APK jogável nem uma biblioteca para importar no APK
do Zelda.** O nome e o export separados impedem que o carregador Zelda a aceite
como `liblasgame.so`. Os estados do relatório são `generated_requires_runtime`
e `linked_requires_runtime`, sempre com `boot_tested=false` e `runtime_ready=false`.

Próxima etapa: adaptar carregador, dispatcher, inicializadores e serviços ao
perfil Mario, usando o executável real. Módulos NSO adicionais são relacionados
em `additional_nso_modules` e ainda precisam de integração própria.

Todo código gerado do jogo fica em `build/`, ignorado pelo Git. Não publicar
essa biblioteca ou os arquivos gerados a partir do jogo.
