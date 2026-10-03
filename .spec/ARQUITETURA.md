# ARQUITETURA — Evolução da aplicação RAG (TXT + PDF, PostgreSQL/pgvector)

Status: **proposta aprovada para documentação; nada implementado.**
Base: análise do código descrito no [README.md](README.md).

## 1. Objetivos e restrições

- Aceitar **apenas** arquivos `.txt` e `.pdf` (PDF só com texto selecionável, **sem OCR**).
- Usar **PostgreSQL** como banco vetorial (extensão **pgvector**).
- Manter o **SentenceTransformer** (`BAAI/bge-m3`) como modelo de embeddings, com melhorias.
- Revisar o chunking e adotar uma estratégia mais eficiente como padrão.
- Interface **somente CLI**, unificada.
- Manter a finalidade de estudo: os conceitos (chunking, busca semântica, lexical, híbrida) continuam visíveis e comparáveis.
- Suportar **várias pastas** de documentos, indexadas uma a uma, com **todas consultadas juntas** (com filtro opcional por pasta).
- **Reindexação incremental** por pasta: só processa arquivos novos ou alterados.
- Suportar **arquivos grandes** (PDFs de centenas de páginas) sem estourar memória (seção 6.1).
- Menu interativo na CLI além dos comandos diretos.

## 2. Decisão: evoluir ou refazer?

**Evoluir.** A divisão em camadas (`chunking`, `embeddings`, `generation`, `fusion`) está boa, e o prompt de geração é sólido (só contexto, citações, defesa contra injection). O que muda de verdade é armazenamento e entrada:

| Hoje | Evolução |
|---|---|
| `vector_store.py` (numpy + JSON) | Repositório Postgres + pgvector |
| `lexical_search.py` (BM25 em memória) | Busca textual do Postgres (`tsvector`, config `portuguese`) |
| Leitura de TXT dentro dos pipelines | Módulo `loaders` (TXT e PDF) |
| `rag.py` + `hybrid_rag.py` | Um único pipeline |
| Scripts soltos | CLI unificada |

## 3. Embeddings — manter SentenceTransformer + `BAAI/bge-m3`

O modelo é adequado: multilíngue (bom em português), 1024 dimensões, contexto de até 8192 tokens, e gera vetores normalizados (cosseno = produto escalar). Não há motivo para trocar. Melhorias:

- `Embedder` com `device` automático (MPS no Mac, senão CPU), `batch_size` configurável e `max_seq_length` explícito.
- Carregar o modelo **uma vez** por processo.
- Gravar nome e dimensão do modelo em `app_meta` na **primeira** vetorização, sem nunca sobrescrever. Se `EMBEDDING_MODEL` mudar, a vetorização é **bloqueada** com a orientação de **reindexar** (vetores de modelos diferentes não são comparáveis); a checagem do nome ocorre antes de carregar o modelo (F04).
- `embed_chunks(embedder, chunks)` vetoriza `Chunk.embedding_text` em fluxo e lotes (padrão 64). Trecho acima de `max_seq_length` (8192 tokens) gera **aviso**, sem bloquear (F04).
- Observação: o bge-m3 também tem modos esparso e multi-vetor, mas isso exige outra biblioteca (FlagEmbedding). Fica **fora do escopo**; a parte lexical é coberta pelo Postgres.

## 4. Ingestão de arquivos

Novo módulo `src/loaders.py` com `inspect_document(path) -> DocumentInfo` (valida o arquivo, calcula o `sha256` e conta as páginas), `iter_pages(path)` (entrega uma `Page` por vez, para PDFs grandes) e `load_document(path) -> Document` (tudo em memória, para arquivos pequenos):

- `Document`: `filename`, `file_type`, `sha256`, `pages: list[Page]` (`Page`: `number`, `text`). `DocumentInfo`: `filename`, `file_type`, `sha256`, `page_count`.
- **TXT**: leitura em UTF-8, com fallback para `utf-8-sig`/`latin-1`. Todo o texto vira a página 1.
- **PDF**: `pymupdf4llm` (PyMuPDF) converte cada página em **Markdown**, preservando títulos e tabelas. O número da página fica como metadado.
- PDF sem texto extraível (provável escaneado): erro claro, sem indexar.
- Qualquer outra extensão: rejeitada com mensagem explícita.
- **Reindexação incremental** (identidade = caminho do arquivo, mudança = `sha256`):
  - arquivo novo → indexa;
  - mesmo caminho e mesmo hash → ignora (idempotente);
  - mesmo caminho e hash diferente → apaga os chunks antigos e reindexa, tudo em uma transação;
  - **conteúdo duplicado** (mesmo `sha256` de um documento já indexado em outro caminho, mesma pasta ou outra) → **ignorado**, sem gerar chunks. O resumo da ingestão informa "duplicado de `<caminho do original>`". O índice único em `sha256` garante isso também no banco;
  - se um arquivo existente for editado e o novo conteúdo for idêntico ao de outro documento, os chunks antigos são removidos e o arquivo é reportado como duplicado;
  - se o original sair do banco (`--prune` ou `delete`), um duplicado antes ignorado passa a ser indexado na próxima ingestão ou reindexação (cobre o caso de arquivo movido de pasta);
  - arquivo sumiu da pasta → removido do banco só com `--prune` (nunca por padrão);
  - `--force` reindexa tudo.
- **Várias pastas:** cada pasta indexada é registrada em `sources`. Pode-se indexar uma a uma, em vezes diferentes. A busca (`ask`) usa **todos** os documentos de todas as pastas por padrão, com filtro opcional `--folder <pasta>`.
- Extensões são casadas sem diferenciar maiúsculas (`.PDF`); arquivos de outros formatos na pasta são listados como ignorados.

## 5. Chunking

**Manter** as 4 estratégias atuais (`fixed`, `sentence`, `recursive`, `semantic`) como material de estudo e comparação, com estas correções:

- `recursive_chunks`: não perder pontuação ao dividir por `". "`.
- `split_sentences`: tratar abreviações comuns e números (ex.: "Sr.", "R$ 1.000,00").
- `semantic_chunks`: impor `min_chars` e `max_chars`.

**Novo padrão proposto: chunking estruturado por Markdown (`structured_chunks`).**

1. Divide o documento por títulos (`#`, `##`, `###`), mantendo a hierarquia.
2. Dentro de cada seção, divide por parágrafo, depois por sentença e só por último por tamanho (a lógica recursiva atual).
3. Cada chunk guarda o **caminho do título** (ex.: `Manual do Colaborador > Férias`). Esse caminho entra como prefixo do texto usado no embedding e na busca textual, mas o conteúdo exibido ao usuário continua limpo.
4. Tamanho alvo ~800–1000 caracteres (~200–250 tokens), overlap ~10–15%, com o limite validado em tokens pelo tokenizer do bge-m3.
5. Tabelas de PDF não são partidas no meio de uma linha.
6. Metadados por chunk: `source`, `page`, `section`, `chunk_index`.
7. Tipo `Chunk(chunk_index, page, section, content)` com `embedding_text` (seção + conteúdo); entrada única `chunk_pages(pages, strategy, ...)`. Um trecho **nunca cruza a fronteira de página**; a seção continua valendo nas páginas seguintes (ver F03).

**Por quê:** PDFs e TXT com títulos perdem contexto quando o chunk não diz a que seção pertence ("o limite é R$ 120" sem saber que é refeição). O prefixo de seção melhora a recuperação, e a divisão por estrutura evita cortes no meio de ideias.

**Não vamos presumir que é melhor: vamos medir.** Um script de avaliação (`scripts/experiments/eval_retrieval.py`) usa um conjunto de perguntas com o trecho esperado e compara as estratégias por **hit rate@k** e **MRR**.

## 6. PostgreSQL + pgvector

### Esquema (`sql/001_init.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE sources (              -- pastas registradas para indexação
  id              BIGSERIAL PRIMARY KEY,
  path            TEXT NOT NULL UNIQUE,   -- caminho absoluto da pasta
  recursive       BOOLEAN NOT NULL DEFAULT true,
  last_indexed_at TIMESTAMPTZ
);

CREATE TABLE documents (
  id          BIGSERIAL PRIMARY KEY,
  source_id   BIGINT REFERENCES sources(id) ON DELETE CASCADE,  -- NULL = arquivo avulso
  source_path TEXT NOT NULL UNIQUE,   -- caminho absoluto do arquivo
  filename    TEXT NOT NULL,
  file_type   TEXT NOT NULL CHECK (file_type IN ('txt', 'pdf')),
  sha256      TEXT NOT NULL,          -- detecta arquivo alterado
  pages       INT  NOT NULL,
  status      TEXT NOT NULL DEFAULT 'indexed' CHECK (status IN ('indexing', 'indexed', 'failed')),
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX documents_sha256_uniq ON documents (sha256);  -- conteúdo duplicado é ignorado (seção 4)

CREATE TABLE chunks (
  id          BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INT    NOT NULL,
  page        INT,
  section     TEXT,
  content     TEXT   NOT NULL,
  embedding   vector(1024) NOT NULL,
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED,
  UNIQUE (document_id, chunk_index)
);

CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_gin        ON chunks USING gin (tsv);

CREATE TABLE app_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL      -- embedding_model, embedding_dim
);
```

A dimensão `1024` é a do bge-m3. Trocar de modelo com outra dimensão exige nova migração.

### Busca híbrida dentro do Postgres

Duas consultas candidatas (`fetch_k`, padrão 10 a 20) combinadas por **RRF em SQL**:

```sql
WITH semantic AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(q)s) AS rank
  FROM chunks ORDER BY embedding <=> %(q)s LIMIT %(fetch_k)s
),
lexical AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv, query) DESC) AS rank
  FROM chunks, websearch_to_tsquery('portuguese', %(text)s) query
  WHERE tsv @@ query
  ORDER BY ts_rank_cd(tsv, query) DESC LIMIT %(fetch_k)s
)
SELECT c.*, COALESCE(1.0/(60+s.rank),0) + COALESCE(1.0/(60+l.rank),0) AS score
FROM chunks c
LEFT JOIN semantic s ON s.id = c.id
LEFT JOIN lexical  l ON l.id = c.id
WHERE s.id IS NOT NULL OR l.id IS NOT NULL
ORDER BY score DESC LIMIT %(top_k)s;
```

- Métodos expostos: `rrf` (padrão), `semantic`, `lexical`. O `weighted` pode permanecer como opção didática, calculado em Python.
- Isso resolve o tokenizer sem acentos: a config `portuguese` do Postgres cuida de acentos, stemming e stopwords.
- **Atenção a validar:** códigos como `E-5107` podem ser tokenizados de forma diferente pelo `to_tsvector`. Isso será verificado manualmente com o documento de exemplo. Se falhar, a alternativa é uma coluna adicional com `simple`.
- Busca vetorial inicialmente **exata** nas verificações com poucos documentos, com HNSW para volume maior (ajuste de `ef_search` se necessário).

### 6.1 Arquivos grandes

Estimativa de ordem de grandeza (a medir na fase 1/3): um PDF de 500 páginas gera cerca de 1.500 a 2.500 chunks. O gargalo é o **embedding no Mac**, não o Postgres: o bge-m3 é um modelo grande (~570M parâmetros) e a indexação desse PDF pode levar de alguns minutos a algumas dezenas de minutos, conforme o hardware. Medidas previstas:

- **Processamento em fluxo:** o PDF é lido página a página; o texto é dividido em chunks e processado em lotes (ex.: 64 chunks por lote), sem manter o documento inteiro em memória.
- **Gravação por lote** (`COPY` ou `executemany`) em vez de um INSERT por chunk.
- **Barra de progresso** (páginas/chunks processados e tempo estimado).
- **Retomada:** `documents.status` (`indexing`/`indexed`/`failed`) permite detectar uma ingestão interrompida e refazê-la; o documento só passa a `indexed` quando termina, e nunca aparece parcial nas buscas (a busca filtra por `status = 'indexed'`).
- **Limites configuráveis:** tamanho máximo de arquivo e de páginas (padrão a definir) com mensagem clara ao exceder.
- **Falha isolada:** um arquivo corrompido não interrompe a indexação da pasta; vai para `failed` com o motivo em `error` e aparece no resumo final.
- Índice HNSW: a criação é incremental, e para cargas muito grandes é possível criá-lo depois da carga inicial.

### Camada de acesso

- `psycopg` 3 + `psycopg_pool` + `pgvector` (adaptador de vetor). SQL explícito, **sem ORM**.
- `src/db.py` (conexão e migração) e `src/repository.py` (`add_document`, `add_chunks`, `search`, `list_documents`, `delete_document`).
- Ingestão de um documento em **uma transação** (documento e chunks gravados juntos ou nada).

## 7. Geração

Mantém o `Generator` e o prompt atuais, com ajustes:

- Se a recuperação retornar vazio (ou abaixo de um limiar mínimo de relevância configurável), responde a frase padrão **sem chamar o LLM**.
- Fontes citadas com **arquivo e página**, no contexto enviado ao LLM e na saída da CLI.
- Ler a resposta filtrando blocos `type == "text"`, em vez de `content[0].text`.

## 8. CLI unificada — `python -m src.cli`

| Comando | Função |
|---|---|
| `init-db` | Confere conexão e extensão `vector` e aplica `sql/001_init.sql` (idempotente, em uma transação). O modelo de embeddings é gravado em `app_meta` pela **F04**, não aqui. |
| `ingest <arquivo\|pasta> [--recursive/--no-recursive] [--force] [--prune]` | Indexa um arquivo ou uma pasta (incremental, ver seção 4). Pastas são registradas em `sources`. |
| `reindex [<pasta>\|--all] [--prune]` | Reprocessa as pastas registradas, só arquivos novos ou alterados. |
| `ask "<pergunta>" [--method rrf\|semantic\|lexical] [--top-k N] [--folder <pasta>]` | Recupera e responde sobre **todas** as pastas (ou só a filtrada), mostrando fontes (arquivo, página, score). |
| `folders` | Lista pastas registradas, nº de documentos e data da última indexação. |
| `list [--folder <pasta>]` | Lista documentos, status e quantidade de chunks. |
| `delete <arquivo\|pasta>` | Remove o documento (ou todos os da pasta) e seus chunks. Pede confirmação. |
| `check` | Verifica variáveis do `.env`, conexão, extensão, tabelas e índices (F01). A verificação dos embeddings (F04) compara o `EMBEDDING_MODEL` do `.env` com o registrado em `app_meta` e a dimensão, sem carregar o modelo; a do Claude entra na **F07**. |
| `menu` (padrão sem argumentos) | Menu interativo (abaixo). |

### Menu interativo

Menu numerado em terminal puro (`input()`, sem dependência extra), que reutiliza os mesmos serviços dos comandos:

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
```

A opção 5 abre um modo de conversa que mantém o método e o filtro de pasta até o usuário sair.

Os scripts atuais de comparação passam para `scripts/experiments/`, adaptados ao novo repositório.

## 9. Configuração e dependências

`.env` / `.env.example`:

```
ANTHROPIC_API_KEY=
HF_TOKEN=
LLM_MODEL=
EMBEDDING_MODEL=BAAI/bge-m3
DATABASE_URL=postgresql://rag_user:<SENHA>@localhost:5432/rag_training_db
```

Banco: `rag_training_db`; usuário: `rag_user`. A **senha fica só no `.env`** (que está no `.gitignore`), nunca neste arquivo nem no `.env.example`, que usa o placeholder `<SENHA>`.

(O `.env.example` já usa `LLM_MODEL`; a variável antiga `MODEL` foi corrigida.)

Adicionar a `requirements.txt`, cada pacote junto da feature que o usa: `psycopg[binary]` (F01), `psycopg_pool` e `pgvector` (F05/F06) e `pymupdf4llm` (F02). Remover `rank-bm25` ao final.

## 10. Estrutura alvo

```
.spec/                 (NEGOCIO.md, ARQUITETURA.md, ROADMAP.md, features/_TEMPLATE.md e as specs FNN-*.md)
src/
  config.py  loaders.py  chunking.py  embeddings.py
  db.py  repository.py  retrieval.py  generation.py  pipeline.py  cli.py
sql/setup_admin.sql    (preparação manual, uma vez: usuário, banco e extensão; exige superusuário)
sql/001_init.sql
scripts/experiments/   (compare_chunking, compare_methods, eval_retrieval…)
data/                  (documentos de exemplo)
```

`retrieval.py` concentra os métodos de busca e a fusão; `pipeline.py` substitui `rag.py` e `hybrid_rag.py`.

## 11. Fases de implementação

0. **Ambiente:** pgvector 0.8.7 já instalado via Homebrew (Postgres 18.6); falta criar o banco `rag_training_db` e o usuário `rag_user`, e `CREATE EXTENSION vector` (a criação da extensão exige superusuário ou permissão equivalente, então é feita uma vez pelo administrador do Postgres).
1. **Loaders** TXT/PDF + verificação manual (PDF de amostra com texto e um sem texto).
2. **Camada Postgres:** `db.py`, `repository.py`, `init-db`.
3. **Ingestão e CLI** (`ingest`, `list`, `delete`).
4. **Busca híbrida em SQL** + `ask`, com paridade de resultados com o comportamento atual para as perguntas do manual.
5. **Chunking estruturado** + script de avaliação (hit rate/MRR); decidir o padrão com base nos números.
6. **Limpeza do legado:** remover `vector_store.py`, `lexical_search.py`, `rag.py` e `hybrid_rag.py`. **`data/index/` é mantido** (decisão do usuário), assim como o `data/manual_colaborador.txt`.

## 12. Critérios de aceite

- `ingest` aceita `.txt` e `.pdf` e rejeita outros formatos; PDF sem texto gera erro claro.
- Reingerir o mesmo arquivo não duplica chunks; arquivo alterado substitui os chunks antigos; `reindex` só reprocessa o que mudou.
- O mesmo conteúdo em dois caminhos (mesma pasta ou pastas diferentes) é indexado uma única vez, e o duplicado é informado no resumo.
- Indexar duas pastas diferentes e perguntar sem filtro usa documentos das duas; com `--folder` usa só a escolhida.
- Um PDF grande (a definir, ex.: 300+ páginas) é indexado com progresso visível, sem consumo de memória proporcional ao arquivo inteiro, e uma falha no meio não deixa documento parcial nas buscas.
- `ask` devolve resposta com citações e fontes contendo arquivo e página.
- Perguntas de exemplo do manual (`E-5107`, "posso trabalhar de casa", limite de refeição) retornam o chunk correto em `rrf`.
- Sem contexto relevante, a resposta é a frase padrão e **nenhuma chamada ao LLM é feita**.
- Trocar `EMBEDDING_MODEL` sem reindexar gera um aviso claro.
- **Sem testes automatizados:** todos os testes são **manuais**, executados conforme os critérios de aceite de cada feature (ver seção 14).

## 13. Pontos a confirmar (não assumidos)

- Limites padrão de tamanho de arquivo/páginas (seção 6.1).
- Layout real dos PDFs (colunas, tabelas, cabeçalhos e rodapés repetidos): só é possível validar com amostras do usuário. Pode ser necessário remover cabeçalhos e rodapés repetidos.
- Limiar mínimo de relevância e tamanho final dos chunks: serão definidos com a avaliação da fase 5, não de antemão.

Resolvidos: banco `rag_training_db`, usuário `rag_user` (senha só no `.env`); `data/index/` não será removido; **arquivos duplicados (mesmo `sha256`) são ignorados**; **pgvector 0.8.7** (Homebrew) confirmado instalado, com Postgres 18.6.

## 14. Estratégia de testes

**Decisão:** não haverá testes unitários nem automatizados (sem `pytest` e sem pasta `tests/`). Toda validação é **manual**.

- Cada spec de feature segue o template `.spec/features/_TEMPLATE.md`, cuja **seção 9** traz os **critérios de aceite escritos como roteiro manual**: passos, comando a executar e resultado esperado. A seção 10 lista os roteiros de outras features a repetir (regressão) e a seção 14 registra a execução.
- Os roteiros usam arquivos de exemplo versionados (`data/manual_colaborador.txt`) e PDFs de amostra, incluindo um PDF sem texto e um arquivo corrompido.
- Um banco separado para experimentos pode ser criado manualmente quando for preciso testar sem afetar a base principal.
- Como não há rede de segurança automática, o código deve falhar de forma **clara** (mensagens explícitas) e cada feature deve ser verificada logo após implementada, antes de seguir para a próxima.
- Risco aceito: mudanças futuras podem quebrar comportamentos antigos sem aviso. A mitigação é repetir os roteiros das features anteriores que forem afetadas.
