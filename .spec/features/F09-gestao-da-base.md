# F09 — Gestão da base

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada (2026-10-10) |
| **Marco** | M2 — Base completa |
| **Depende de** | F05 (`repository`, `documents`, `chunks`), F08 (`sources`, `source_id`, trava por pasta, confirmação `[s/N]`) |
| **Regras de negócio** | R10 (e R9 na remoção) |
| **Seções da arquitetura** | §6 (esquema), §8 (`folders`, `list`, `delete`), §14 Testes |

## 1. Objetivo
A pessoa passa a **ver o que está na base** (pastas e documentos) e a **remover** documentos ou pastas inteiras, sempre depois de uma confirmação explícita. Completa a regra R10 (a F08 só cobriu o `--prune`).

## 2. Escopo

**Inclui**
- `folders`: lista as pastas registradas, com nº de documentos, nº de trechos e data da última indexação.
- `list [--folder <pasta>]`: lista os documentos (caminho, tipo, páginas, trechos, status), todos ou só os de uma pasta.
- `delete <arquivo|pasta>`: remove um documento, ou todos os de uma pasta registrada (e o registro da pasta), com listagem prévia e confirmação `[s/N]`.
- Remoção atômica (R9): documento, trechos e, se for o caso, registro da pasta saem juntos ou nada sai.
- Trava por pasta (F08, T5) também na remoção, para não competir com um `ingest`/`reindex` da mesma pasta.

**Não inclui** (fica para outra feature ou fora de escopo)
- Menu interativo (F10).
- Apagar arquivos do disco: a aplicação **nunca** toca nos arquivos originais.
- Remover o **registro** de uma pasta sem remover seus documentos (não há esse caso de uso; ver seção 11).
- Remover uma **subpasta** não registrada (só pastas registradas em `sources`).
- Troca de `EMBEDDING_MODEL` e limpeza de `app_meta` (continua pendência futura do ROADMAP).
- Opção `--yes` para pular a confirmação (ver seção 11).
- Alterar o `--prune` da F08.

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R10 | Antes de **remover** documentos ou pastas, a aplicação lista o que será removido e **pede confirmação**. Só `s` ou `S` confirma. Sem terminal interativo, não remove. |
| R9 | A remoção é **uma transação**: nunca sobra documento sem trechos, trechos sem documento ou pasta pela metade. |
| R4 | Depois de remover, o mesmo conteúdo pode ser cadastrado de novo (o `sha256` sai da base junto com o documento). |
| R6 | Continua valendo: sumir do disco não remove da base. Só `delete` (ou `--prune`) remove. |

**Regras técnicas**
- **T1. Resolução do alvo de `delete`.** O argumento vira caminho absoluto resolvido (como no `ingest`). Ordem:
  1. é o `source_path` de um documento cadastrado → **documento**;
  2. é o `path` de uma pasta registrada → **pasta**;
  3. senão → erro (4.2). Não é necessário que o caminho exista em disco (permite remover o que já sumiu).
- **T2. Remover pasta.** Apaga o registro em `sources`; os documentos da pasta saem por `ON DELETE CASCADE` (`documents.source_id`) e os trechos por `ON DELETE CASCADE` (`chunks.document_id`). Documentos avulsos (`source_id` nulo) **não** são afetados.
- **T3. Remover documento.** Apaga o documento (trechos em cascata). Se o documento pertence a uma pasta, a pasta continua registrada; a próxima atualização o cadastra de novo se o arquivo ainda existir (isso é esperado).
- **T4. Confirmação.** Mostra o alvo e a contagem (documentos e trechos), lista os documentos (até 20; acima disso, os 20 primeiros e `… e mais N`) e pergunta `[s/N]`. Enter, `n`, EOF ou `Ctrl+C` = nada removido. Sem terminal interativo (`stdin` e `stdout`), recusa sem remover, código 1.
- **T5. Trava.** Ao remover uma pasta, ou um documento que pertence a uma pasta, toma a trava da F08 (`try_lock_folder`) **antes** de confirmar e a mantém até o fim. Se não conseguir, recusa na hora (mesma mensagem da F08).
- **T6. `list` e `folders` são somente leitura.** Não carregam o modelo de embeddings, não exigem `ANTHROPIC_API_KEY` e não tomam trava.
- **T7. Filtro `--folder` do `list`** usa o mesmo critério da F06 (`folder_prefix`: prefixo do caminho). Aceita qualquer pasta, registrada ou não (subpasta, por exemplo). Caminho resolvido como no `ingest`.
- **T8. Ordem.** `folders`: pelo cadastro (`sources.id`). `list`: por caminho.
- **T9.** Importar os módulos novos não carrega o modelo, não conecta ao banco e não exige `.env`.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. `python -m src.cli folders` mostra as pastas registradas (e a linha de documentos avulsos, se houver).
2. `python -m src.cli list` (ou `list --folder <pasta>`) mostra os documentos.
3. `python -m src.cli delete <arquivo|pasta>` resolve o alvo (T1), toma a trava se preciso (T5), mostra o que será removido e pede confirmação (T4).
4. Com `s`, remove numa transação e informa o que saiu. Código 0.

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| `folders` sem pastas registradas | Código 0. | `Nenhuma pasta registrada. Cadastre com: python -m src.cli ingest <pasta>` |
| `folders` com documentos avulsos | Última linha da tabela. | `(avulsos)` com a contagem |
| `list` com base vazia | Código 0. | `Nenhum documento na base.` |
| `list --folder` sem documentos naquela pasta | Código 0. | `Nenhum documento em <pasta>.` |
| `delete` de caminho que não é documento nem pasta registrada | Erro, nada alterado. Código 1. | `<caminho> não está na base. Veja os documentos com: python -m src.cli list` |
| `delete` de subpasta de pasta registrada (não registrada) | Mesmo erro acima, com dica. Código 1. | `<caminho> não é uma pasta registrada. Para remover um arquivo, informe o arquivo; para a pasta, informe a pasta registrada (<pasta>).` |
| `delete` confirmado | Remove (T2/T3). Código 0. | `Removido: N documento(s), M trecho(s).` e, se pasta, `Pasta <pasta> removida do registro.` |
| `delete` recusado (`n`, Enter, EOF) | Nada removido. Código 0. | `Nada foi removido.` |
| `Ctrl+C` na confirmação | Nada removido. Código 1. | `Remoção cancelada.` |
| `delete` sem terminal interativo | Nada removido. Código 1. | `delete exige confirmação em um terminal interativo; nada foi removido.` |
| Pasta com atualização em andamento (T5) | Recusa na hora. Código 1. | `Já existe uma atualização da pasta <pasta> em andamento. Tente novamente quando ela terminar.` |
| Pasta registrada sem documentos | Remove só o registro, após confirmação. | `Pasta <pasta> (0 documentos).` e `Pasta <pasta> removida do registro.` |
| Falha de banco durante a remoção | Transação desfeita, nada removido. Código 1. | Mensagem do banco da F01 |
| Banco indisponível ou tabelas ausentes | Erro da F01. Código 1. | `Tabela documents ausente. Execute init-db.` |
| `delete` sem argumento | Erro de `argparse`. Código 2. | — |

### 4.3 Saída para a pessoa

```
$ python -m src.cli folders
PASTA                                 RECURSIVA  DOCS  TRECHOS  ÚLTIMA INDEXAÇÃO
/Users/.../docs                       sim           9       63  2026-10-09 14:32
/Users/.../notas                      não           2       11  2026-10-08 09:10
(avulsos)                             —             1        7  —
```

```
$ python -m src.cli list --folder /Users/.../docs
CAMINHO                                TIPO  PÁG  TRECHOS  STATUS
/Users/.../docs/guia.md                md      1        5  indexed
/Users/.../docs/manual.txt             txt     1        7  indexed
/Users/.../docs/politica.pdf           pdf    40       51  indexed

3 documento(s), 63 trecho(s).
```

```
$ python -m src.cli delete /Users/.../docs
Pasta: /Users/.../docs (3 documento(s), 63 trecho(s))
  /Users/.../docs/guia.md
  /Users/.../docs/manual.txt
  /Users/.../docs/politica.pdf
Os arquivos no disco não serão apagados. A pasta deixará de ser registrada.
Remover? [s/N] s
Removido: 3 documento(s), 63 trecho(s).
Pasta /Users/.../docs removida do registro.
```

## 5. Interface

**Comandos / opções da CLI**

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `folders` | — | Lista as pastas registradas. |
| `list` | `[--folder <pasta>]` | Lista os documentos. |
| `delete` | `<arquivo\|pasta>` | Remove documento ou pasta registrada, com confirmação. |

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/repository.py` | Consultas e remoções (reuso de `list_sources`, `get_source`, `find_by_path`, `remove_document`, `list_documents_of_source`, `folder_prefix`, `try_lock_folder`, `unlock_folder`) | **Novas:** `list_documents(conn, folder: str \| None) -> list[DocumentListing]` (com nº de trechos), `source_stats(conn) -> list[SourceStats]` (docs, trechos por pasta e avulsos), `remove_source(conn, source_id) -> None` |
| `src/management_service.py` (novo) | Regras de `folders`, `list` e `delete` (resolver alvo, travar, confirmar via callback, remover numa transação) | `list_folders()`, `list_documents(folder)`, `delete_target(target, confirm) -> DeleteResult` |
| `src/cli.py` | Subcomandos `folders`, `list`, `delete`, tabelas e `_confirm_delete` (reaproveita a checagem de terminal do `_confirm_prune`) | `cmd_folders`, `cmd_list`, `cmd_delete` |

## 6. Dados
**Sem mudanças.** As remoções usam as cascatas já existentes (`documents.source_id` → `sources`, `chunks.document_id` → `documents`, ambas `ON DELETE CASCADE`). A contagem de trechos vem de `count(*)` em `chunks`.

## 7. Configuração
**Sem mudanças.** Limite de 20 linhas na lista de confirmação é constante do código (T4), não variável do `.env`.

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| Linhas listadas na confirmação | 20 | Constante em `src/cli.py` |

## 8. Dependências externas
Nenhuma. Sem pacotes novos em `requirements.txt`.

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:**
- Banco inicializado (`init-db` ok) e modelo de embeddings configurado (para cadastrar os dados de teste).
- Pasta de teste `<teste>/docs` com `manual.txt`, `guia.md` e `politica.pdf` (com texto), cadastrada com `ingest <teste>/docs`.
- Um segundo arquivo avulso `<teste>/avulso.txt`, cadastrado com `ingest <teste>/avulso.txt`.
- Uma segunda pasta `<teste>/notas` com 1 arquivo, cadastrada.

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | Listar pastas | `python -m src.cli folders` | Duas pastas com docs, trechos, recursiva e data; linha `(avulsos)` com 1 documento. Código 0. |
| 2 | Listar todos os documentos | `python -m src.cli list` | Todos os documentos (pastas e avulso), ordem por caminho, tipos `txt`/`md`/`pdf`, status `indexed`, contagem total no fim. |
| 3 | Filtrar por pasta | `list --folder <teste>/docs` | Só os 3 documentos da pasta. |
| 4 | Filtrar por subpasta ou pasta não registrada | `list --folder <teste>/docs/sub` (com arquivos cadastrados ali) | Só os documentos com aquele prefixo; sem nenhum: `Nenhum documento em <pasta>.` |
| 5 | Base vazia (banco de teste vazio) | `folders` e `list` | `Nenhuma pasta registrada…` e `Nenhum documento na base.` Código 0. |
| 6 | Alvo inexistente | `delete <teste>/nao-existe.txt` | `… não está na base…`, nada alterado, código 1. |
| 7 | Recusar a remoção de um documento | `delete <teste>/docs/manual.txt`, responder `n` | Mostra o documento e os trechos, `Nada foi removido.`, `list` ainda o mostra. |
| 8 | Remover um documento | `delete <teste>/docs/manual.txt`, responder `s` | `Removido: 1 documento(s), N trecho(s).`; a pasta continua registrada; `list` não o mostra; `search` por um termo exclusivo dele não o retorna. |
| 9 | Remover um documento cujo arquivo já sumiu do disco | Apagar `guia.md` do disco; `delete <teste>/docs/guia.md`, `s` | Remove normalmente (T1). |
| 10 | Cadastrar de novo o mesmo conteúdo (R4) | `ingest <teste>/docs/manual.txt` | `cadastrado` (não `duplicado`). |
| 11 | Remover o avulso | `delete <teste>/avulso.txt`, `s` | Remove; `(avulsos)` some de `folders`. |
| 12 | Subpasta não registrada | `delete <teste>/docs/sub` | Mensagem que aponta a pasta registrada. Código 1. |
| 13 | Sem terminal interativo | `echo s \| python -m src.cli delete <teste>/docs` | `delete exige confirmação em um terminal interativo; nada foi removido.` Código 1; nada removido. |
| 14 | `Ctrl+C` na confirmação | `delete <teste>/docs`, pressionar `Ctrl+C` | `Remoção cancelada.` Código 1; nada removido. |
| 15 | Trava da pasta | Em um terminal, `ingest` de pasta grande; em outro, `delete` da mesma pasta | `delete` recusa com `Já existe uma atualização da pasta…`. |
| 16 | Remover a pasta | `delete <teste>/docs`, `s` | Lista os documentos; remove docs, trechos e registro; `folders` não mostra mais a pasta; arquivos no disco intactos; outra pasta e o avulso continuam. |
| 17 | Pasta registrada sem documentos | `ingest` de pasta vazia e `delete` dela | Confirma e remove só o registro. |
| 18 | Atomicidade | Conferir no SQL (abaixo) após o passo 16 | Nenhum documento órfão e nenhum trecho órfão. |
| 19 | Lista longa | Pasta com mais de 20 documentos, `delete` e responder `n` | Mostra 20 e `… e mais N`; nada removido. |
| 20 | Banco sem tabelas | `list` com banco sem `init-db` | `Tabela documents ausente. Execute init-db.` Código 1. |
| 21 | Somente leitura | `list` e `folders` sem `ANTHROPIC_API_KEY` e com `EMBEDDING_MODEL` inválido | Funcionam; o modelo não é carregado (T6). |

**Consultas úteis para conferir o banco**
```sql
SELECT count(*) FROM chunks c LEFT JOIN documents d ON d.id = c.document_id WHERE d.id IS NULL;   -- esperado: 0
SELECT path FROM sources ORDER BY id;
SELECT source_path, source_id FROM documents ORDER BY source_path;
```

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F05 | Passos de duplicado e de cadastro de arquivo avulso | A remoção libera o `sha256`; duplicados voltam a poder ser cadastrados. |
| F06, F07 | Passo de busca com e sem `--folder` | Documentos removidos não podem aparecer em `search` nem em `ask`. |
| F08 | Passos de `--prune`, `reindex` e trava | `delete` usa a mesma trava e a mesma confirmação; pasta removida deixa de ser reindexada por `reindex --all`. |
| F01 | `check` | Sem mudanças esperadas; confirmar que continua `ok`. |

## 11. Riscos e decisões

**Decisões tomadas** (com o motivo)
- **Remover pasta apaga também o registro em `sources`**: o `ON DELETE CASCADE` já faz isso e manter uma pasta registrada vazia faria o `reindex --all` recadastrar tudo sem a pessoa ter pedido.
- **`delete` aceita arquivo ou pasta registrada**, como no CLI alvo da ARQUITETURA; subpasta não registrada é recusada para evitar apagar "metade" de uma pasta registrada.
- **Sem terminal interativo, não remove**, igual ao `--prune` (F08): uma remoção nunca deve acontecer por acidente em um script.
- **Nunca apaga arquivos do disco**: a base é um índice; os originais pertencem à pessoa.
- **Remover um documento de uma pasta registrada é permitido** e esperado que o `reindex` o traga de volta (T3).

**Pontos em aberto** (resolvidos: o usuário aprovou as propostas abaixo)
1. Aceitar `--yes` para remover sem perguntar (útil em scripts)? **Proposta:** não, para manter a R10 inequívoca nesta fase.
2. Remover uma **subpasta** de pasta registrada (todos os documentos com aquele prefixo) deve ser possível? **Proposta:** não nesta feature.
3. `list` deve mostrar também `error` e `updated_at`? **Proposta:** não; `status` basta (`failed`/`indexing` não são gravados hoje).
4. Caminhos na tabela: absolutos (como acima) ou relativos à pasta registrada? **Proposta:** absolutos, por serem inequívocos e iguais ao que o `delete` aceita.

## 12. Documentação a atualizar
- `.spec/ROADMAP.md`: status da F09 e do marco M2.
- `.spec/ARQUITETURA.md`: tabela da CLI (`folders`, `list`, `delete`) marcada como implementada, sem `--folder` em `delete`.
- `.claude/CLAUDE.md`: incluir F09 na lista de features implementadas.
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
