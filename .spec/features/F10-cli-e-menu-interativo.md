# F10 — CLI e menu interativo

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada (2026-10-10) |
| **Marco** | M3 — Uso pela equipe |
| **Depende de** | F01 (`check`), F06 (`run_search`), F07 (`run_ask`), F08 (`ingest`, `reindex`), F09 (`folders`, `list`, `delete`) |
| **Regras de negócio** | R10 (a confirmação de remoção vem da F09), R11 (aviso de envio ao Claude vem da F07) |
| **Seções da arquitetura** | §8 (CLI e menu interativo), §14 Testes |

## 1. Objetivo
A pessoa abre `python -m src.cli` em um terminal e **faz tudo por um menu numerado**: indexar e reindexar pastas, ver o que há na base, perguntar, remover e verificar o ambiente, sem decorar comandos. Os comandos diretos continuam funcionando; o menu só **reúne** a lógica que já existe.

## 2. Escopo

**Inclui**
- `python -m src.cli` sem argumentos abre o **menu** quando `stdin` e `stdout` são um terminal interativo; caso contrário imprime a ajuda e sai com código 0.
- Menu numerado com 8 itens (seção 4.3), em terminal puro (`input()`), repetido até a pessoa escolher `0`.
- **Modo conversa** (item 5): várias perguntas em sequência, mantendo método e filtro de pasta, com o modelo de embeddings carregado **uma vez**.
- Escolha de pasta por **lista numerada** das pastas registradas (itens 2, 4 e 6 e no filtro do modo conversa).
- Atualização do texto da ajuda (sem argumentos) para citar o menu.
- Adaptação de `run_search` e `run_ask` para aceitar um modelo de embeddings já carregado.

**Não inclui** (fica para outra feature ou fora de escopo)
- Qualquer lógica nova de cadastro, busca, resposta ou remoção: o menu chama o que já existe.
- `--force` e `--prune` no menu (ficam só na CLI direta).
- Histórico de conversa: cada pergunta é independente (NEGOCIO §8).
- Avaliação de qualidade (F11) e remoção do código antigo (F12).
- Menu fora do terminal (API, web), cores, bibliotecas de interface.
- Escolher `--top-k` e `--fetch-k` no menu (ver seção 11).

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R10 | O item 6 usa a mesma confirmação `[s/N]` da F09; nada é removido sem ela. |
| R11 | Cada pergunta do modo conversa avisa que os trechos encontrados serão enviados ao Claude (serviço externo), como no `ask`. |
| R4, R5, R6, R9 | Continuam valendo: o menu chama `ingest` e `reindex` da F08, sem alterar o comportamento. |

**Regras técnicas**
- **T1. Abertura.** Sem argumentos: se `sys.stdin.isatty()` e `sys.stdout.isatty()`, abre o menu; senão imprime a ajuda e sai com código 0. Com argumentos, o comportamento atual não muda.
- **T2. Reuso.** Cada item do menu chama a mesma função de comando (`cmd_ingest`, `cmd_reindex`, `cmd_folders`, `cmd_list`, `cmd_delete`, `cmd_check`) com um `argparse.Namespace` montado pelo menu. A saída é a dos comandos diretos. Nenhuma regra é reescrita.
- **T3. Erros não derrubam o menu.** Mensagens de erro dos comandos aparecem como hoje (em `stderr`) e a pessoa volta ao menu. O código de saída dos comandos é ignorado pelo menu; o menu termina com código 0.
- **T4. `Ctrl+C`.** Durante uma operação: a operação é interrompida como nos comandos diretos (com a mensagem deles) e volta ao menu. No prompt do menu: sai com código 0. Em fim de entrada (EOF), sai com código 0.
- **T5. Entrada inválida.** Opção fora do menu ou vazia: `Opção inválida.` e mostra o menu de novo.
- **T6. Lista numerada de pastas.** Mostra as pastas registradas (`management_service.list_folders()`, sem a linha dos avulsos) numeradas a partir de 1, e a pessoa digita o número. Número inválido ou vazio cancela a operação e volta ao menu. Sem pastas registradas, informa e volta ao menu (4.2).
- **T7. Item 1 (indexar pasta).** Pede o caminho da pasta e executa como `ingest <pasta>` sem opções (`--recursive` segue o padrão e o valor guardado da F08, T8). Se o caminho for um arquivo, também funciona como `ingest <arquivo>` (o menu não distingue).
- **T8. Item 6 (remover).** Pergunta `1) Pasta registrada  2) Documento`. Pasta: lista numerada (T6). Documento: pede o caminho digitado. Executa `delete <alvo>`, que pede a confirmação da F09.
- **T9. Modo conversa.**
  - Ao entrar, mostra o método (`rrf` por padrão) e a pasta (`todas`).
  - Cada linha digitada é uma pergunta, respondida como o `ask` (mesma saída, R11 incluído). Linha vazia é ignorada.
  - O modelo de embeddings é carregado na **primeira pergunta que precisa dele** e reaproveitado nas seguintes (método `lexical` não carrega o modelo).
  - Não há histórico: uma pergunta não enxerga as anteriores.
  - Erros (`AskError`, `SearchError`, `GenerationError`, `EmbeddingError`, `DbError`) são mostrados e a conversa continua; só `/sair` ou `Ctrl+C`/EOF no prompt encerram.
  - A pasta e o método ficam guardados na sessão e só mudam pelos comandos da seção 5.
- **T10. Modelo reutilizável.** `run_search` e `run_ask` ganham um parâmetro opcional de origem do modelo. Sem ele, o comportamento é o de hoje (carrega a cada chamada), e `search` e `ask` diretos não mudam.
- **T11. Item 7 (verificar ambiente).** Executa o mesmo que `check` e mostra a saída dele.
- **T12.** Importar `src/menu.py` não carrega o modelo, não conecta ao banco e não exige `.env`. Itens que dependem de modelo ou do SDK do Claude importam o que precisam só ao serem usados.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. A pessoa executa `python -m src.cli` em um terminal.
2. O menu aparece e pede uma opção.
3. A pessoa escolhe um item; a operação roda, mostrando a saída do comando equivalente.
4. O menu aparece de novo. `0` encerra com código 0.

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| `python -m src.cli` sem terminal interativo (pipe, script) | Imprime a ajuda e sai. Código 0. | Ajuda da CLI (inclui a linha sobre o menu) |
| Opção inexistente ou vazia | Volta ao menu. | `Opção inválida.` |
| Itens 2 ou 6 (pasta) sem pastas registradas | Volta ao menu. | `Nenhuma pasta registrada. Cadastre com a opção 1 do menu.` |
| Número de pasta inválido ou vazio | Cancela, volta ao menu. | `Operação cancelada.` |
| Item 1 com caminho vazio | Cancela, volta ao menu. | `Operação cancelada.` |
| Erro do comando (banco, modelo, pasta inexistente, trava) | Mostra a mensagem do comando e volta ao menu. | Mensagem original da feature de origem |
| `Ctrl+C` durante a operação | A operação para como no comando direto e volta ao menu. | Mensagem da feature de origem (ex.: `Atualização interrompida; …`) |
| `Ctrl+C` ou EOF no prompt do menu | Encerra. Código 0. | (linha em branco) |
| Item 4 com base vazia | Mostra o que `folders` e `list` mostram. | `Nenhuma pasta registrada…` / `Nenhum documento na base.` |
| Item 5 com base vazia | Mostra a mensagem do `ask` e **continua** na conversa. | `A base está vazia. Cadastre um arquivo com: python -m src.cli ingest <arquivo>` |
| Item 5 sem `ANTHROPIC_API_KEY` ou `LLM_MODEL` | Mostra o erro do `ask` ao perguntar; a conversa continua. | `<VARIÁVEL> não definida. Copie .env.example para .env e preencha.` |
| Comando desconhecido no modo conversa (começa com `/`) | Mostra a ajuda do modo e continua. | Lista dos comandos da seção 5 |
| `/metodo` com valor inválido | Mantém o método atual. | `Método inválido. Use rrf, semantic ou lexical.` |
| `/pasta` com número inválido | Mantém a pasta atual. | `Número de pasta inválido.` |
| Item 6 com confirmação recusada | Nada removido, volta ao menu. | `Nada foi removido.` |

### 4.3 Saída para a pessoa

```
=== RAG Training ===
1) Adicionar/indexar pasta
2) Reindexar uma pasta
3) Reindexar todas as pastas
4) Listar pastas e documentos
5) Fazer uma pergunta
6) Remover pasta ou documento
7) Verificar ambiente
0) Sair
Opção: 2

Pastas registradas:
  1) /Users/.../docs/api
  2) /Users/.../docs/application
Escolha o número da pasta (Enter cancela): 1
Pasta:      /Users/.../docs/api (já registrada | recursiva: sim)
…
```

Modo conversa:
```
Opção: 5
Modo conversa | método: rrf | pasta: (todas)
Comandos: /metodo <rrf|semantic|lexical>, /pasta, /sair
Pergunta> Quantos dias de férias?
Os trechos encontrados serão enviados ao Claude (serviço externo).
Pergunta:  Quantos dias de férias?
Método:    rrf | top-k 5 | fetch-k 20 | pasta: (todas)

Resposta:
…
Fontes:
[1] manual.txt | página 1 | Férias
Tempo: 3,2 s (busca 0,9 s, resposta 2,3 s)
Pergunta> /sair
```

## 5. Interface

**Comandos / opções da CLI** (e item de menu)

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m src.cli` (sem argumentos) | — | Abre o menu em terminal interativo; sem terminal, imprime a ajuda. |
| Item 1 | caminho digitado | Equivale a `ingest <pasta>`. |
| Item 2 / 3 | número da pasta / nenhum | Equivalem a `reindex <pasta>` / `reindex --all`. |
| Item 4 | pasta opcional (lista numerada, Enter = todas) | Equivale a `folders` seguido de `list [--folder]`. |
| Item 5 | — | Modo conversa (T9). |
| Item 6 | pasta (lista numerada) ou documento (caminho) | Equivale a `delete <alvo>`. |
| Item 7 | — | Equivale a `check`. |

**Comandos do modo conversa** (linha começando com `/`)

| Comando | Efeito |
|---|---|
| `/metodo <rrf\|semantic\|lexical>` | Troca o método da sessão. Sem argumento, mostra o atual. |
| `/pasta` | Mostra a lista numerada de pastas; o número escolhido vira o filtro da sessão. Enter mantém. Opção `0` volta a `(todas)`. |
| `/sair` | Volta ao menu. |

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/menu.py` (novo) | Laço do menu, leitura de opções, lista numerada de pastas, modo conversa | `run_menu() -> int`, `_choose_folder(prompt) -> str \| None`, `_conversation()` |
| `src/cli.py` | Chama `run_menu()` quando não há subcomando e há terminal; texto da ajuda; extrai a execução e a impressão do `ask` para uma função reutilizada pelo menu | `main`, `_ask_and_print(question, method, top_k, fetch_k, folder, embedder_source)` (extraída de `cmd_ask`, sem mudar a saída) |
| `src/search_service.py`, `src/answer_service.py` | Parâmetro opcional com a origem do modelo de embeddings, reaproveitada entre perguntas (T10) | `run_search(..., embedder_source=None)`, `run_ask(..., embedder_source=None)`, `EmbedderCache` (carrega o modelo uma vez) |

## 6. Dados
**Sem mudanças.**

## 7. Configuração
**Sem mudanças.** Método inicial do modo conversa: `rrf`; `top-k` e `fetch-k`: os padrões do `ask` (F07).

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| Método inicial da conversa | `rrf` | Constante em `src/menu.py` |
| `top-k` / `fetch-k` da conversa | 5 / 20 | Padrões de `src/retrieval.py` |

## 8. Dependências externas
Nenhuma. Sem pacotes novos em `requirements.txt`.

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:**
- Banco inicializado, com pelo menos uma pasta de teste registrada (com 2 ou 3 arquivos) e um arquivo avulso cadastrado.
- `ANTHROPIC_API_KEY` e `LLM_MODEL` definidos no `.env`.
- **Usar um banco de teste** para os passos que removem dados (itens 6 e 12).

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | Ajuda sem terminal | `python -m src.cli \| cat; echo $?` | Imprime a ajuda (com a linha sobre o menu) e código 0; o menu não abre. |
| 2 | Abrir o menu | `python -m src.cli` | Menu da seção 4.3 aparece. |
| 3 | Opção inválida | Digitar `9`, depois Enter vazio | `Opção inválida.` nas duas vezes; o menu volta. |
| 4 | Sair | Digitar `0` | Encerra; `echo $?` mostra 0. |
| 5 | `Ctrl+C` e EOF no menu | `Ctrl+C`; em outra execução, `Ctrl+D` | Encerra com código 0. |
| 6 | Item 1: pasta | Opção `1` e o caminho da pasta de teste | Saída igual à de `ingest <pasta>`; volta ao menu. |
| 7 | Item 1: caminho vazio e inexistente | Enter vazio; depois um caminho inexistente | `Operação cancelada.`; depois a mensagem de erro do `ingest`; o menu volta nas duas. |
| 8 | Item 2: reindexar uma pasta | Opção `2`, número da pasta | Saída igual à de `reindex <pasta>`. |
| 9 | Item 2: número inválido | Opção `2`, digitar `99` | `Operação cancelada.` |
| 10 | Item 3: reindexar todas | Opção `3` | Saída igual à de `reindex --all`. |
| 11 | Item 4: listar | Opção `4`, Enter (todas); repetir escolhendo uma pasta | Tabela de pastas e de documentos; com pasta, só os documentos dela. |
| 12 | Item 6: remover | Opção `6`, `1` (pasta), número, responder `n`; repetir respondendo `s` (banco de teste) | Com `n`: `Nada foi removido.`; com `s`: pasta e documentos removidos e `folders` não a mostra. |
| 13 | Item 6: documento | Opção `6`, `2`, caminho do avulso, `s` (banco de teste) | Documento removido; volta ao menu. |
| 14 | Item 7: verificar | Opção `7` | Mesma saída de `check`. |
| 15 | Item 5: pergunta | Opção `5`, fazer uma pergunta sobre um documento | Aviso de envio ao Claude, resposta e fontes como no `ask`; o prompt `Pergunta>` volta. |
| 16 | Modelo carregado uma vez | No item 5, fazer duas perguntas seguidas | A segunda não repete a carga do modelo (resposta bem mais rápida na etapa de busca). |
| 17 | Sem histórico | Perguntar "e o prazo dela?" depois de uma pergunta sobre outro assunto | A resposta não usa a pergunta anterior (pode dizer que não encontrou). |
| 18 | Trocar método | `/metodo lexical`, perguntar; `/metodo xyz` | A saída mostra `Método: lexical`; o inválido mantém o atual com a mensagem. |
| 19 | Filtrar pasta | `/pasta`, escolher uma; perguntar sobre um documento de outra pasta | A saída mostra `pasta: <pasta>`; a pergunta fora dela não encontra. `/pasta` + `0` volta a `(todas)`. |
| 20 | Linha vazia e comando desconhecido | Enter vazio; `/foo` | Vazia é ignorada; `/foo` mostra a ajuda do modo. |
| 21 | Sair da conversa | `/sair` | Volta ao menu. |
| 22 | Conversa com base vazia (banco de teste vazio) | Opção `5`, qualquer pergunta | Mensagem de base vazia e a conversa continua. |
| 23 | Erro sem derrubar | Remover `ANTHROPIC_API_KEY` do `.env`; opção `5` e uma pergunta | Mensagem do `ask`; a conversa continua. |
| 24 | Itens 2 e 6 sem pastas (banco de teste vazio) | Opção `2` e opção `6` → `1` | `Nenhuma pasta registrada. Cadastre com a opção 1 do menu.` |

**Consultas úteis para conferir o banco**
```sql
SELECT path, last_indexed_at FROM sources ORDER BY id;
SELECT count(*) FROM documents;
```

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F01 | Passo 1 (ajuda da CLI) | O texto da ajuda ganha a linha do menu e a ajuda sem argumentos passa a depender de terminal interativo. A spec da F01 (seção 4.2) também deve ser atualizada. |
| F06 | Passos de `search` direto, com e sem `--folder` | `run_search` ganha parâmetro opcional. |
| F07 | Passos de `ask` direto (resposta, fontes, base vazia, pasta sem documentos) | `cmd_ask` passa a usar `_ask_and_print` extraída e `run_ask` ganha parâmetro. A saída não pode mudar. |
| F08, F09 | Passos de `ingest`, `reindex`, `folders`, `list`, `delete` diretos | O menu monta os argumentos e chama as mesmas funções. |

## 11. Riscos e decisões

**Decisões tomadas** (com o motivo)
- Sem argumentos e com terminal, abre o menu; sem terminal, imprime a ajuda (código 0): scripts e pipes nunca ficam presos esperando entrada.
- A ajuda ganha uma linha sobre o menu, para a pessoa descobri-lo.
- Pastas escolhidas por lista numerada (itens 2, 4 e 6): evita erro de digitação de caminhos longos.
- Item 1 usa só o padrão do `ingest`; `--force` e `--prune` ficam na CLI direta, onde o `--prune` já tem a sua confirmação.
- Modo conversa mantém só método e pasta, sem histórico (NEGOCIO §8), e carrega o modelo uma vez.
- O menu chama os comandos existentes (T2): uma única implementação de cada operação.

**Pontos em aberto:** nenhum. Resolvidos na aprovação, com as propostas do rascunho:
1. Método e pasta mudam no modo conversa por `/metodo`, `/pasta` e `/sair` (seção 5).
2. `top-k` e `fetch-k` ficam nos padrões (5/20) no modo conversa.
3. Sem pausa entre operações: o menu reaparece na hora.
4. A lista numerada de pastas ignora os documentos avulsos; eles aparecem só em `folders`/`list`.

## 12. Documentação a atualizar
- `.spec/features/F01-ambiente-e-banco.md`: seção 4.2 (comando sem argumentos) e passo 1 do roteiro.
- `.spec/ARQUITETURA.md`: linha `menu` da tabela da CLI e o bloco do menu, marcando como implementado.
- `.spec/ROADMAP.md`: status da F10.
- `.claude/CLAUDE.md`: incluir a F10 na lista de features.
- `README.md`: só na F12.

## 13. Definição de pronto
- [x] Spec aprovada pela pessoa responsável
- [x] Código implementado somente no que a spec descreve
- [x] Todos os passos do roteiro (seção 9) executados e aprovados
- [x] Roteiros de regressão (seção 10) repetidos
- [x] Documentação da seção 12 atualizada
- [x] Status atualizado nesta spec e no ROADMAP

## 14. Registro de verificação

| Data | Quem executou | Resultado | Observações / falhas encontradas |
|---|---|---|---|
| 2026-10-10 | Jose Julio | Aprovado | Roteiro da seção 9 executado pela pessoa responsável; regressão da seção 10 informada como repetida. |
