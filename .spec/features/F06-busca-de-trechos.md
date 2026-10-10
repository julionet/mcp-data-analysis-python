# F06 — Busca de trechos

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada |
| **Marco** | M1 — Fatia vertical |
| **Depende de** | F01 (esquema), F04 (`Embedder`, conferência do modelo), F05 (trechos e vetores gravados) |
| **Regras de negócio** | R9 (só documentos cadastrados por completo aparecem); base para R2 (cada trecho traz documento e página) |
| **Seções da arquitetura** | §6 (busca híbrida em SQL, `tsv`), §8 (`ask`), §14 Testes |

## 1. Objetivo
Dada uma pergunta, devolver os **trechos mais relevantes** da base, combinando **significado** (vetores) e **palavras exatas** (texto), em português e inglês, com filtro opcional por pasta. É a etapa de recuperação que a resposta com fontes (F07) vai consumir. Nesta feature **não há chamada ao Claude**: a pessoa vê os trechos, as fontes e as pontuações.

## 2. Escopo

**Inclui**
- Comando `search "<pergunta>"` na CLI, que mostra os trechos encontrados.
- Três métodos: `rrf` (padrão, semântico + textual fundidos), `semantic` e `lexical`.
- Busca textual em **português e inglês** (decisão pendente do ROADMAP): nova migração `sql/003_busca_textual.sql`.
- Filtro opcional `--folder <pasta>`, por prefixo do caminho do arquivo.
- Módulo `src/retrieval.py` com a função de busca reutilizável pela F07.
- Só trechos de documentos com `status = 'indexed'` (R9).
- `check` e `init-db` passam a cobrir o que a migração 003 cria.

**Não inclui**
- Gerar a resposta com o Claude, citar fontes na resposta e o "não encontrei" (F07).
- Limiar mínimo de relevância (F07 usa; o valor padrão sai da F11). A F06 só devolve as pontuações.
- Tabela `sources` e cadastro de pastas (F08). O filtro por pasta funciona pelo caminho do arquivo, sem depender dela.
- Método `weighted` (média ponderada) e reordenação (rerank).
- Ajuste fino de `fetch_k`, `top_k` e `hnsw.ef_search` (F11).
- Menu interativo (F10) e o comando `ask` (F07).

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R9 | Só entram na busca trechos de documentos `indexed`. Um cadastro interrompido nunca aparece (já garantido pela transação da F05; a consulta filtra por `status` mesmo assim). |
| R2 (base) | Cada resultado traz `arquivo`, `página` e `seção`, para a F07 citar a fonte. |
| R1 (base) | A busca só devolve conteúdo da base. Não usa nenhum conhecimento externo. |

**Regras técnicas**
- **T1.** O vetor da pergunta vem do mesmo `EMBEDDING_MODEL` registrado em `app_meta`. Divergência: erro, como na F04, **antes** de carregar o modelo.
- **T2.** O método `lexical` **não carrega o modelo**: roda só com o banco (rápido).
- **T3.** Semântico: ordena por distância de cosseno (`<=>`); o `score` mostrado é a **similaridade** (`1 − distância`, de −1 a 1).
- **T4.** Textual: um trecho casa se o texto (português **ou** inglês) tem ao menos um termo da pergunta; `score` = `ts_rank_cd` (o maior entre os dois idiomas). Termos são combinados com **OU** (ver seção 11). Antes de montar as consultas, as palavras da pergunta que são **palavras vazias em português ou em inglês** (ex.: `de`, `o`, `e`, `the`, `can`) são descartadas; as demais viram radical em cada idioma.
- **T5.** `rrf`: cada método devolve até `fetch_k` candidatos; `score = Σ 1/(60 + posição)` nos métodos em que o trecho apareceu.
- **T6.** Empates são desempatados por `chunk.id`, para o resultado ser determinístico.
- **T7.** O filtro de pasta casa pelo **prefixo de caminho** (`pasta/`), sem tratar `%` e `_` como curingas.
- **T8.** Importar `src.retrieval` não carrega modelo nem conecta ao banco.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. A pessoa executa `python -m src.cli search "posso trabalhar de casa?"`.
2. A aplicação conecta ao banco e confere se há documentos `indexed`.
3. Para `semantic` e `rrf`: confere `EMBEDDING_MODEL` x `app_meta`, carrega o modelo, confere a dimensão e vetoriza a pergunta.
4. Executa a consulta SQL do método (seção 6) com o filtro de pasta, se houver.
5. Mostra os `top_k` melhores trechos (padrão 5), com posição, pontuação, arquivo, página, seção e o texto.

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| Nenhum trecho encontrado | Sem erro. Código 0. | `Nenhum trecho encontrado.` |
| Base sem documentos cadastrados | Código 0, sem carregar o modelo. | `A base está vazia. Cadastre um arquivo com: python -m src.cli ingest <arquivo>` |
| `--folder` sem nenhum documento naquela pasta | Código 0. | `Nenhum documento cadastrado em <pasta>.` |
| `--folder` não existe no disco | Aceito (a base pode ter documentos de um caminho antigo). O resultado segue a regra acima. | — |
| Pergunta vazia ou só espaços | Erro. Código 1. | `Informe a pergunta.` |
| `--method` inválido, `--top-k` ou `--fetch-k` ≤ 0 | Erro de argumento (`argparse`). Código 2. | Mensagem do `argparse` |
| `--top-k` > `--fetch-k` | `fetch_k` sobe para `top_k`. | — |
| Modelo configurado ≠ registrado, `EMBEDDING_MODEL` ausente, modelo não carrega, dimensão ≠ 1024 | Erros da F04. Código 1. Em `lexical` não ocorrem (T2). | Mensagens da F04 |
| Banco indisponível ou esquema/migração ausente | Erro claro. Código 1. | `DbError` da F01; migração 003 ausente: `Busca textual desatualizada. Execute init-db.` |
| Pergunta só com palavras vazias (ex.: "de a o") | O ramo textual não gera termos e fica vazio; `rrf` usa só o semântico. Em `lexical`, vazio. | `Nenhum trecho encontrado.` |
| Pergunta com aspas, `-`, `:` ou outros símbolos | Tratada como texto comum, sem erro de sintaxe. | — |
| Pergunta em inglês sobre documento em português (e o inverso) | O semântico acha por significado; o textual só casa palavras do mesmo idioma. | — |
| Documento `indexing` ou `failed` | Nunca aparece (R9). | — |

### 4.3 Saída para a pessoa
```
$ python -m src.cli search "posso trabalhar de casa?" --top-k 3
Pergunta:  posso trabalhar de casa?
Método:    rrf | top-k 3 | fetch-k 20 | pasta: (todas)
Resultados: 3 em 0,4 s

#1  score 0,0328 | semântico #1 (0,56) · textual #1 (0,08)
    manual_colaborador.txt | página 1 | Manual do Colaborador — Acme Tech > Trabalho remoto
    A Acme Tech adota o modelo híbrido. Os colaboradores trabalham presencialmente às terças e quintas e remotamente …

#2  score 0,0161 | semântico #2 (0,44)
    manual_colaborador.txt | página 1 | Manual do Colaborador — Acme Tech > Férias
    Colaboradores CLT têm direito a 30 dias corridos de férias …
```
- `semantic`: mostra `similaridade 0,56`. `lexical`: mostra `textual (ts_rank_cd 0,08)`.
- O texto é cortado em 240 caracteres; `--full` mostra o trecho inteiro.
- Erros em `stderr`, código 1, sem traceback.

## 5. Interface

**Comandos / opções da CLI**

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m src.cli search` | `"<pergunta>"` `[--method rrf\|semantic\|lexical]` `[--top-k N]` `[--fetch-k N]` `[--folder <pasta>]` `[--full]` | Mostra os trechos mais relevantes (4.3). Padrões: `rrf`, `top-k 5`, `fetch-k 20`. |
| `python -m src.cli init-db` / `check` | — | `init-db` aplica a 003; `check` confere as colunas e os índices novos. |

O `ask` (F07) reaproveitará `retrieval.search`. Sem item de menu (F10).

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/retrieval.py` | Busca nos três métodos, em SQL. | `search(conn, text, vector, method="rrf", top_k=5, fetch_k=20, folder=None) -> list[SearchHit]`; `SearchHit(chunk_id, document_id, source_path, filename, page, section, content, score, semantic_rank, semantic_score, lexical_rank, lexical_score)`; `METHODS = ("rrf", "semantic", "lexical")`. `vector` é `None` em `lexical`. |
| `src/search_service.py` | Orquestra: base vazia, conferência do modelo, vetorização da pergunta, chamada à busca. | `run_search(text, method, top_k, fetch_k, folder) -> SearchOutcome` (hits + metadados da execução); `SearchError` |
| `src/cli.py` | Subcomando `search` e formatação. | `cmd_search(args)` |
| `src/db.py` | `check_environment` e `EXPECTED_INDEXES` ampliados. | — |
| `sql/003_busca_textual.sql` | Migração (seção 6). | — |

Detalhes:
- O vetor é enviado como `vector` (adaptador `pgvector` da F05).
- A consulta usa `SET LOCAL hnsw.iterative_scan = relaxed_order` (pgvector 0.8) para o filtro de pasta e de `status` não esvaziar o resultado quando o índice HNSW é usado.
- A consulta `lexical` monta as duas `tsquery` (português e inglês) no SQL: separa a pergunta em palavras (`to_tsvector('simple', …)`), descarta as que são palavras vazias em `portuguese_stem` **ou** `english_stem` (`ts_lexize` devolve `{}`) e junta o resto com OU (`|`) em `to_tsquery` de cada idioma.

## 6. Dados

**Migração `sql/003_busca_textual.sql`** (idempotente; roda na ordem da 001 e 002). Duas colunas geradas, uma por idioma, ambas sobre **seção + conteúdo**, com a seção em peso menor (`C`) e o conteúdo em peso maior (`A`), para que palavras de título repetidas em todos os trechos pesem menos que as do corpo:

```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'chunks' AND column_name = 'tsv_en') THEN
    ALTER TABLE chunks DROP COLUMN tsv;   -- leva junto chunks_tsv_gin
    ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS
      (setweight(to_tsvector('portuguese', coalesce(section, '')), 'C') ||
       setweight(to_tsvector('portuguese', content), 'A')) STORED;
    ALTER TABLE chunks ADD COLUMN tsv_en tsvector GENERATED ALWAYS AS
      (setweight(to_tsvector('english', coalesce(section, '')), 'C') ||
       setweight(to_tsvector('english', content), 'A')) STORED;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS chunks_tsv_gin    ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_tsv_en_gin ON chunks USING gin (tsv_en);
```
Os trechos já gravados são recalculados pelo próprio banco (colunas geradas). Sem mudança em `documents`, `app_meta` e nos vetores.

**Consultas (esboço):**

```sql
-- semântico
SELECT c.id, 1 - (c.embedding <=> %(q)s) AS score
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE d.status = 'indexed' AND (%(folder)s IS NULL OR starts_with(d.source_path, %(folder)s))
ORDER BY c.embedding <=> %(q)s, c.id LIMIT %(fetch_k)s;

-- textual
WITH words AS (   -- palavras da pergunta, sem as vazias de nenhum dos dois idiomas
  SELECT w FROM unnest(tsvector_to_array(to_tsvector('simple', %(text)s))) w
  WHERE ts_lexize('portuguese_stem', w) IS DISTINCT FROM '{}'
    AND ts_lexize('english_stem', w)    IS DISTINCT FROM '{}'),
q AS (
  SELECT to_tsquery('portuguese', string_agg(quote_literal(w), ' | ')) AS pt,
         to_tsquery('english',    string_agg(quote_literal(w), ' | ')) AS en
  FROM words)
SELECT c.id, GREATEST(ts_rank_cd(c.tsv, q.pt), ts_rank_cd(c.tsv_en, q.en)) AS score
FROM chunks c JOIN documents d ON d.id = c.document_id, q
WHERE d.status = 'indexed' AND (c.tsv @@ q.pt OR c.tsv_en @@ q.en)
  AND (%(folder)s IS NULL OR starts_with(d.source_path, %(folder)s))
ORDER BY score DESC, c.id LIMIT %(fetch_k)s;
```
`rrf` junta os dois resultados (`FULL OUTER JOIN` pelas posições `ROW_NUMBER()`) e soma `1/(60 + posição)`.

`EXPECTED_INDEXES` em `src/db.py` ganha `chunks_tsv_en_gin`. `check` falha se a coluna `chunks.tsv_en` não existir (`Execute init-db`).

## 7. Configuração
Sem variáveis novas.

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| `top_k` | 5 | Constante em `src/retrieval.py`; `--top-k` |
| `fetch_k` | 20 | Constante em `src/retrieval.py`; `--fetch-k` |
| Constante do RRF | 60 | Constante em `src/retrieval.py` |
| Trecho exibido | 240 caracteres | Constante na CLI; `--full` |
| Limiar mínimo de relevância | Não existe nesta feature | F07 / F11 |

## 8. Dependências externas
- Nenhum pacote novo.
- PostgreSQL com o esquema da F01, a migração 002 (F13) e a nova 003; configurações de busca `portuguese` e `english` (já vêm com o Postgres).
- Dados de teste: `data/manual_colaborador.txt`, `data/amostras/guia.md`, `data/amostras/com_texto.pdf` e **amostra nova a criar**: `data/amostras/remote_policy.md`, um texto curto em **inglês** com 2 títulos (política de trabalho remoto e um código de erro, ex.: `ERR-7712`).

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** ambiente virtual ativo; comandos na raiz; `init-db` aplicado (inclui a 003); base **limpa** (`DELETE FROM documents;`) e cadastrados `manual_colaborador.txt`, `guia.md`, `remote_policy.md` e `com_texto.pdf` com `ingest`.

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | Migração | `python -m src.cli init-db` e `check` | `init-db` informa a atualização da busca textual; `check` sem falhas; novamente `init-db`: `Esquema já estava atualizado.` |
| 2 | Colunas e índices | Consulta 1 | `tsv`, `tsv_en` e os dois índices GIN existem; `tsv` e `tsv_en` preenchidos nos trechos já gravados. |
| 3 | Híbrido, significado | `search "posso trabalhar de casa?"` | Trecho **Trabalho remoto** em 1º; mostra arquivo, página, seção, `semântico` e `textual`; código 0. |
| 4 | Híbrido, código exato | `search "E-5107"` | Trecho de **Suporte de TI** com E-5107 em 1º (textual casa o código). |
| 5 | Semântico | `search "posso trabalhar de casa?" --method semantic` | Mesmo trecho em 1º, com `similaridade`; sem coluna textual. |
| 6 | Lexical, sem modelo | `search "E-5107" --method lexical` | Resultado correto **sem carregar o modelo** (resposta em menos de ~1 s, sem a linha "Loading weights"). |
| 7 | Semântico erra o código, lexical acerta | Comparar o passo 4 em `semantic` x `lexical` | `lexical` coloca o trecho do código em 1º; `semantic` pode não colocar. Registrar a posição de cada um. |
| 8 | Português: radical | `search "limite de refeições" --method lexical` | Casa o trecho de Reembolso (`refeições` x `Refeições`, plural e acento). |
| 9 | Inglês: radical | `search "working remotely" --method lexical` | Casa o trecho em inglês de `remote_policy.md` (`work`/`remote`). |
| 10 | Código em inglês | `search "ERR-7712" --method lexical` | Trecho de `remote_policy.md` em 1º. |
| 11 | Pergunta em inglês, documento em português | `search "can I work from home?" --method semantic` | O trecho **Trabalho remoto** (português) aparece entre os 3 primeiros. |
| 12 | Pergunta em português, documento em inglês | `search "política de trabalho remoto" --method semantic` | O trecho de `remote_policy.md` aparece entre os 3 primeiros. |
| 13 | Palavras do título | `search "reembolso" --method lexical` | Trecho da seção **Reembolso de despesas** aparece (a seção entra na busca textual, com peso menor). |
| 13b | Peso do título | `search "Acme" --method lexical --top-k 10` e `search "Reembolso" --method lexical` | `Acme` (só no título do documento) devolve trechos do manual com pontuação **menor** que a de uma palavra do corpo; confirmar na pontuação mostrada. Registrar as pontuações. |
| 14 | Natural com várias palavras (OU) | `search "qual o limite diário de refeição na viagem?" --method lexical` | Pelo menos o trecho de Reembolso aparece (com `E` entre os termos, não apareceria). |
| 15 | Filtro de pasta | `search "trabalho remoto" --folder $(pwd)/data/amostras` | Só `guia.md`, `remote_policy.md` e `com_texto.pdf` possíveis; **nenhum** de `data/manual_colaborador.txt`. |
| 16 | Pasta sem documentos | `search "teste" --folder /tmp/nada` | `Nenhum documento cadastrado em /tmp/nada.`; código 0. |
| 17 | Curinga no caminho | `search "teste" --folder "$(pwd)/data/amo%"` | `Nenhum documento cadastrado…` (o `%` não vira curinga). |
| 18 | Sem resultados | `search "xyzzyqwerty" --method lexical` | `Nenhum trecho encontrado.`; código 0. |
| 19 | Só palavras vazias (nos dois idiomas) | `search "de a o" --method lexical` e `search "the of and" --method lexical` | `Nenhum trecho encontrado.`; sem erro. (Sem o filtro de palavras vazias, `de`/`o` casariam quase todo trecho pela coluna em inglês.) |
| 19b | Palavra vazia em português não distorce o ranking | `search "posso trabalhar de casa?" --method lexical --folder $(pwd)/data` | O trecho **Trabalho remoto** em 1º (sem o filtro, Reembolso ficava à frente por causa do `de`). |
| 20 | Símbolos | `search "\"E-5107\" -teste (a:b)"` | Sem erro de sintaxe; código 0. |
| 21 | Pergunta vazia | `search "   "; echo $?` | `Informe a pergunta.`; código 1. |
| 22 | Argumentos inválidos | `search "x" --method foo` e `--top-k 0` | Erro do `argparse`; código 2. |
| 23 | `--top-k` | `search "trabalho" --top-k 2` | No máximo 2 resultados. |
| 24 | `--full` | `search "trabalho remoto" --top-k 1 --full` | Texto do trecho completo, sem corte. |
| 25 | Base vazia | `DELETE FROM documents;` e `search "x"` | `A base está vazia…`; código 0; **sem carregar o modelo**. Recadastrar depois. |
| 26 | R9 | Em transação aberta de outro terminal, ou `UPDATE documents SET status='failed' WHERE id = <um>` | Trechos do documento `failed` **não** aparecem; reverter para `indexed`. |
| 27 | Modelo divergente | `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 python -m src.cli search "teste"; echo $?` | Mensagem da F04, sem baixar o outro modelo; código 1. Em `--method lexical` **funciona**. |
| 28 | Migração ausente | Renomear temporariamente `chunks.tsv_en` (banco de teste) e rodar `search --method lexical` e `check` | Mensagem `Busca textual desatualizada. Execute init-db.`; `check` falha; código 1. Reverter. |
| 29 | Desempate estável | Repetir o passo 3 três vezes | Mesma ordem e mesmas pontuações. |
| 30 | Tempo | Anotar o tempo de `search` com o modelo já em cache e de `--method lexical` | Registrar na seção 14 (sem meta fixa). |
| 31 | Importação sem efeitos | `python -c "import src.retrieval"` | Sem saída, sem carregar modelo nem conectar. |
| 32 | Somente o previsto | `git status` | Só os arquivos previstos. |

**Consultas úteis para conferir o banco**
```sql
-- 1) colunas e índices de busca textual
SELECT column_name FROM information_schema.columns WHERE table_name='chunks' AND column_name IN ('tsv','tsv_en');
SELECT indexname FROM pg_indexes WHERE tablename='chunks' ORDER BY 1;
SELECT count(*) FILTER (WHERE tsv IS NOT NULL), count(*) FILTER (WHERE tsv_en IS NOT NULL), count(*) FROM chunks;
-- como o Postgres tokeniza
SELECT to_tsvector('portuguese','Erro E-5107 em refeições'), to_tsvector('english','working remotely, ERR-7712');
SELECT to_tsquery('portuguese', 'posso | trabalhar | casa'), to_tsquery('english', 'posso | trabalhar | casa');
```

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F01 | `init-db` e `check` | A migração 003 recria `tsv` e cria `tsv_en`; `EXPECTED_INDEXES` mudou. |
| F05 | 1, 6, 11 | `INSERT` em `chunks` não menciona `tsv`/`tsv_en` (colunas geradas): confirmar que o cadastro segue igual. |
| F13 | 2, 4 | A migração 002 continua aplicada; `init-db` com três migrações segue idempotente. |
| F04 | 8 (similaridade) | Os vetores não mudam; serve de referência para o semântico. |
| F07, F08, F09, F11 | — | Passam a usar `retrieval.search` e a nova coluna textual. |

## 11. Riscos e decisões

**Decisões tomadas** (confirmadas pela pessoa)
- **Português e inglês com duas colunas geradas** (`tsv` e `tsv_en`), casando por **OU** entre os idiomas. O custo de espaço e tempo é desprezível e dispensa detectar o idioma de cada documento.
- **Título da seção entra na busca textual com peso menor** (`C`), e o conteúdo com peso `A`. Ganha a busca por palavras de título e reduz o ruído de títulos repetidos. **Revoga** a decisão da F05 de que `tsv` teria só `content`.
- **Filtro de pasta por prefixo de caminho**, sem depender de `sources` (F08); continua válido quando a F08 existir.
- **Palavras vazias de ambos os idiomas são descartadas da pergunta** (decisão da pessoa, após medição): a coluna `tsv_en` indexa o `de`/`o`/`e` dos textos em português como palavras comuns, e eles inflavam o ranking textual (no teste, Reembolso ficou à frente de Trabalho remoto para "posso trabalhar de casa?"). Efeito aceito: uma palavra vazia em só um dos idiomas é descartada nos dois.
- **Termos da pergunta combinados por OU** na busca textual (E zeraria perguntas naturais); o `ts_rank_cd` põe no topo quem casa mais termos e o RRF compensa o ruído.
- **Comando `search` (sem LLM) nesta feature**; `ask` fica para a F07.
- **`lexical` não carrega o modelo** (T2): útil para códigos e para testar sem o custo do modelo.
- **Sem limiar de relevância na F06**: devolve sempre os `top_k` melhores, com a pontuação. O "não encontrei" é da F07, com o valor da F11.
- **`ts_rank_cd`** (e não `ts_rank`): considera a proximidade dos termos.
- **Índice HNSW com filtro:** `hnsw.iterative_scan = relaxed_order` evita resultados faltando quando o filtro elimina vizinhos; com poucos documentos o planejador usa varredura exata.
- **`weighted` e rerank fora**: o RRF cobre o caso, e o legado `src/fusion.py` continua até a F12.

**Riscos aceitos**
- O `to_tsvector` do Postgres tokeniza `E-5107` como `-5107` (o `E` vira palavra vazia no português). Funciona para casar o código, e é o mesmo tratamento na consulta; códigos que só diferem pelo prefixo podem casar entre si. Medir no passo 4 e no 10.
- Uma palavra vazia em só um dos idiomas (ex.: `can`) deixa de ser buscada nos dois. Perguntas em um idioma e documentos no outro dependem só do ramo semântico (passos 11 e 12).
- A migração 003 recalcula `tsv` de todos os trechos (descarte e recriação da coluna). Com a base atual é instantâneo; em base grande leva tempo e bloqueia escrita durante a migração.

**Pontos em aberto**
Nenhum.

## 12. Documentação a atualizar
- `.spec/ROADMAP.md`: status da F06; decisão "busca em português e inglês" passa a resolvida.
- `.spec/ARQUITETURA.md` §6 (esquema com `tsv_en`, consultas e filtro de pasta) e §8 (`search`).
- `.spec/features/F01-ambiente-e-banco.md` e `F05-cadastro-de-documento.md`: nota de que `tsv` mudou (F06).
- `.claude/CLAUDE.md`: acrescentar F06 ao "implementada e verificada" ao concluir.
- `README.md` e `.env.example`: sem mudanças.

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
| 2026-10-09 | Claude (pré-verificação na implementação) | Passos 1–32 executados; resultados abaixo | Aguarda execução e aprovação da pessoa. **Adaptação do roteiro:** a base já tinha documentos reais da pessoa (documentação do Cartsys.Gestor, ids 28–38 e 40), então **não foi feito** `DELETE FROM documents`; os testes usaram `--folder $(pwd)/data` (o que também exercita o filtro) e mexeram só nos 4 documentos de teste. **Medição e correção:** no passo 19 `"de a o"` devolveu 5 trechos e no passo 3 o ramo textual pôs Reembolso à frente de Trabalho remoto, porque `tsv_en` indexa `de`/`o`/`e` do português como palavras comuns. Aplicado o descarte de palavras vazias dos dois idiomas (spec atualizada antes do código); depois: `"de a o"` e `"the of and"` → `Nenhum trecho encontrado.`; "posso trabalhar de casa?" em `lexical` → Trabalho remoto em 1º (3,20 contra 1,00). **Resultados:** híbrido acha Trabalho remoto em 1º (semântico #1 0,56); `E-5107` em 1º no `rrf` e, depois da correção, único resultado no `lexical`; `ERR-7712`, `working remotely`, `reembolso` e `limite de refeições` corretos; PT↔EN no semântico (passos 11 e 12): `remote_policy.md` e Trabalho remoto nas 2 primeiras posições; peso do título (13b): `Acme` só no título pontua 0,20 contra 1,20 no corpo; filtro de pasta, `%` sem curinga, pasta sem documentos, sem resultado, símbolos, pergunta vazia (código 1), argumentos inválidos (código 2), `--top-k` e `--full` ok; ordem estável em 3 execuções. **Passo 25** simulado (`count_indexed` → 0): `empty_base` sem carregar o modelo. **Passo 26:** `guia.md` marcado `failed` não aparece em `lexical` nem `semantic` (controle positivo com `indexed`: aparece); status restaurado. **Passo 28:** com `tsv_en` renomeada numa transação revertida, `DbError: Busca textual desatualizada`; `check` falha sem a coluna e passa depois do `init-db`. **Passo 27:** modelo divergente → mensagem da F04, código 1; `lexical` funciona. **Migração:** recalculo de 197 trechos já gravados confirmado (`tsv` e `tsv_en` preenchidos após recriar `tsv_en`). **Tempos (passo 30):** `rrf` ~10 s (inclui carga do modelo), `lexical` ~0,2 s. **Observação:** em `lexical` perguntas com termos comuns do português que não são palavras vazias (ex.: `posso`) ainda entram na consulta e aumentam pontuações; sem impacto nos testes. |
| 2026-10-09 | Jose Julio | Aprovado | Roteiro da seção 9 aprovado, conforme relato da pessoa. |
