# Auditoria nxnative → ScarletNX: texturas bindless do Castlevania

Data: 2026-10-22. Escopo: somente investigação; **não** alterar runtime, ABI, AOT ou APK funcional.

## Evidência confirmada no código

- nxnative (MIT), `dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Translation/Optimizations/BindlessElimination.cs`: `TryGetOperation` percorre recursivamente entradas `PhiNode` com pilha e conjunto `visited`. `IsSameOperand` reconhece handles equivalentes produzidos por OR de constant buffers e constantes.
- ScarletNX fixado no script Android em `34853eeae5af132e320adbb0193f13344085bf89`, `src/nx/gpu/shader/spirv_translate.c`: `direct_track_image_handle_pair` chama `direct_track_image_handle` e `direct_reaching_def`, com limite de profundidade 6 e rastreamento de `MOV_R`, `MOV_C`, `LDC`, `LOP_R/C`, `IADD_R/C`.
- `direct_reaching_def` recusa definições ambíguas em fronteiras de blocos e mudanças de predicado. É mais conservador que o algoritmo nxnative para caminhos `phi`.
- Pelo menos quatro famílias de instruções chamam `direct_track_image_handle_pair` e rejeitam o shader quando retorna zero: `O_TLD_B`, amostragem bindless, `O_TMML_B` e `O_TXD_B`.
- **Não está demonstrado** que os cinco shaders do Castlevania falham especificamente por `phi`, nem que a mesma estratégia é segura no decoder Maxwell atual.

## Diferenças arquiteturais e riscos

Ryujinx/nxnative opera em IR SSA com `PhiNode` explícito. ScarletNX opera diretamente em instruções Maxwell e fluxo de controle. Copiar `TryGetOperation` em C não basta: é necessário construir predecessores de blocos, provar a equivalência de origens e garantir que nenhum caminho redefine o handle.

A correção correta não pode supor que handles distintos são iguais, nem substituir falhas por um descriptor arbitrário. Isso poderia produzir textura errada, acesso fora dos limites e crash Vulkan.

O próprio ScarletNX é GPL-3.0-or-later; o subconjunto Ryujinx no nxnative declara MIT. Respeitar licenças/atribuições e analisar implicações para distribuição antes de portar.

## Plano de implementação seguro

1. **Diagnóstico primeiro:** registrar, por shader rejeitado, opcode da instrução consumidora, registro de handle, índice da instrução, primeira falha em `direct_reaching_def`, motivo (controle/predicado/definição ambígua/profundidade/opcode não suportado). Limitar volume e não incluir dump de jogo no GitHub.
2. **Testes sintéticos:** construir programas Maxwell curtos cobrindo MOV_C, LDC, MOV_R, OR, ADD, loop com definição equivalente em dois predecessores e caso negativo com definições diferentes.
3. **Análise de fluxo:** construir predecessores de basic blocks, propagar origem de handle `(bank, offset, optional second)` por caminhos com ciclo detectado e ponto fixo; aceitar só quando todas as origens são comprovadamente equivalentes.
4. **Integração:** manter o algoritmo conservador existente como primeiro caminho; usar a análise nova apenas quando ele falhar; recusar ambiguidades e preservar os motivos de rejeição.
5. **Validação:** comparar corpus de shaders, `spirv-val`, contagem de `untracked texture handle`, `draws skipped`, captura da mesma cena e estabilidade no dispositivo. Nenhuma alteração no código AOT dos 1152 blocos.
6. **Isolamento:** compilar apenas na branch `experimental/castlevania-belmonts-curse`, manter runtime e APK de Mario intactos, backup do APK Castlevania anterior.

## Próximo passo bloqueante

Obter diagnóstico da origem do handle nos cinco shaders reais; sem ele, um patch de fluxo de controle seria especulativo. O relatório de log do Castlevania já guarda avisos ao longo da execução; a próxima instrumentação deve ser inserida no rastreador de handles para expor a causa precisa.

Referências:
- https://github.com/seedds/nxnative/blob/main/dm/third_party/ryujinx/README.md
- https://github.com/seedds/nxnative/blob/main/dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Translation/Optimizations/BindlessElimination.cs
- https://github.com/scarletnx/ScarletNX/blob/34853eeae5af132e320adbb0193f13344085bf89/src/nx/gpu/shader/spirv_translate.c
