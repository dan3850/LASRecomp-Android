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
e respeitadas pelo carregador do APK de teste.

## Compilar o APK para tentar o boot

Depois da linkagem bem-sucedida, na mesma cópia de trabalho:

```bash
bash compilar-mario-boot-termux.sh \
  /storage/emulated/0/SwitchRoms/Super-extraido
```

O comando usa a `libmario_test.so` e o `build-report.json` existentes. Verifica
o hash da biblioteca e dos NSOs, gera um perfil com a identidade e as bases
registradas e compila o runtime e o aplicativo. Não executa novamente o gerador
do jogo nem recompila os objetos de `main`/`sdk`. Reaproveita o cache compartilhado
de SDL, Vulkan, FFmpeg e das demais dependências do script Termux existente.
As ferramentas Android e o NDK já configurados para esse script continuam necessários.

O aplicativo é **Mario Recomp TESTE**, pacote `com.retroaura.mario.bootdiag`.
Saídas:

| Arquivo | Conteúdo |
|---|---|
| `build/mario-android-boot/Mario-Recomp-Boot-Test.apk` | APK assinado para a tentativa de inicialização |
| `build/mario-android-boot/compilacao.log` | Log da compilação Android |
| `build/mario-android-boot/profile/mario_boot_profile.json` | Identidade da biblioteca, Build IDs e bases |

Com o acesso do Termux a Downloads configurado, o APK também é copiado para
`Download/MarioRecomp/Mario-Recomp-Boot-Test.apk`.

Instale o APK, selecione `Super-extraido` e toque em **Iniciar teste**.
A pasta precisa conter `exefs/main`, `exefs/sdk`, `exefs/main.npdm` e `romfs/`.
O app usa acesso de leitura via SAF e verifica os Build IDs antes de iniciar.
O runtime repete essa verificação ao carregar os NSOs. O jogo é executado pelo
ciclo SDL Android existente, com o dispatcher e os inicializadores de módulos
do runtime. Serviços HLE ausentes encerram o teste com nome e endereço no log.

O perfil Mario desativa os callbacks de gameplay, patches do randomizer,
leituras de câmera e overlays que dependem dos endereços do Zelda. O menu do
teste fica restrito a controles, vídeo, áudio e saída.

Após uma tentativa, abra o app novamente e use **Ver último log** ou **Salvar
log**. Os registros incluem `lasrecomp_boot.txt` e `lasrecomp.log`, sem copiar
os arquivos do jogo. A geração do APK não comprova que o Mario chegou à tela
inicial: essa confirmação exige executar no aparelho e analisar o resultado.
Módulos adicionais em `additional_nso_modules` bloqueiam esta etapa até existir
suporte explícito para carregá-los.

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

**A linkagem desta biblioteca não comprova que o jogo inicia.** O nome e o
export separados vinculam a biblioteca ao runtime Mario. Os estados do relatório
de geração são `generated_requires_runtime`
e `linked_requires_runtime`, sempre com `boot_tested=false` e `runtime_ready=false`.

Os testes de boot usam a biblioteca sintética existente e os fontes reais de
`gamelib.c`, `loader.c` e `dispatch.c`: verificam chamadas entre `main` e `sdk`,
memória, SIMD, rejeição de Build ID incompatível e falha explícita de HLE ausente.
Esses testes no host não substituem uma compilação completa do APK ou um teste
do executável real no Android. Próximo diagnóstico: o primeiro bloqueio de boot
registrado no aparelho, antes de ampliar serviços ou otimizar o renderer.

Todo código gerado do jogo fica em `build/`, ignorado pelo Git. Não publicar
essa biblioteca ou os arquivos gerados a partir do jogo.
