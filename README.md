# RAG Training (Python)

Aplicação de estudo dos conceitos principais de **RAG** (Retrieval-Augmented Generation). Ela responde perguntas sobre um documento de texto: recupera os trechos mais relevantes e envia só esses trechos ao LLM (Claude).

Escopo atual:

- Entrada: **apenas arquivos TXT**.
- Base vetorial: **arquivos locais** (`numpy` + JSON). Não há banco de dados vetorial.
- Embeddings: **SentenceTransformer**, modelo configurável (exemplo: `BAAI/bge-m3`).
- Busca: semântica, léxica (BM25) e híbrida (RRF e média ponderada).
- Geração: **Claude**, pela SDK `anthropic`.

> A evolução planejada (PDF + PostgreSQL/pgvector) está descrita em [.spec/ARQUITETURA.md](.spec/ARQUITETURA.md).

---

## Arquitetura

```
                 INDEXAÇÃO
 arquivo .txt ─► chunking ─► embeddings ─► VectorStore ─► data/index/
                    │                         (vectors.npy + texts.json)
                    └────────────────────► LexicalSearch (BM25, em memória)

                 CONSULTA
 pergunta ─► embedding ─► busca semântica ┐
        └──► tokenização ► busca BM25     ├─► fusão (RRF / ponderada) ─► top_k chunks
                                          ┘                                  │
                                       resposta com citações [n] ◄─ Claude ◄─┘
```

## Estrutura do projeto

```
src/
  config.py          variáveis de ambiente (.env)
  chunking.py        4 estratégias de divisão de texto
  embeddings.py      classe Embedder (SentenceTransformer)
  vector_store.py    base vetorial em memória, salva em disco
  lexical_search.py  busca BM25
  fusion.py          fusão de rankings (ponderada e RRF)
  generation.py      prompt e chamada ao Claude
  rag.py             pipeline RAG semântico
  hybrid_rag.py      pipeline RAG híbrido
scripts/             scripts executáveis (indexar, perguntar, comparar)
data/
  manual_colaborador.txt   documento de exemplo
  index/                   índice gerado (vectors.npy, texts.json)
```

## Requisitos e instalação

- Python 3.10 ou superior (o código usa `list[str]` e `X | None`).
- Chave da API da Anthropic.
- Na primeira execução, o modelo de embeddings é baixado do Hugging Face.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # depois edite os valores
```

Dependências (`requirements.txt`): `anthropic`, `sentence-transformers`, `rank-bm25`, `numpy`, `python-dotenv`.

### Configuração (`.env`)

| Variável | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API do Claude (obrigatória para `ask`). |
| `HF_TOKEN` | Token do Hugging Face (usado em `check_setup` e `compare_chunking`). |
| `LLM_MODEL` | Modelo do Claude usado na geração. |
| `EMBEDDING_MODEL` | Modelo SentenceTransformer, por exemplo `BAAI/bge-m3`. |

## Uso rápido

Execute sempre da raiz do projeto, com `python -m`:

```bash
python -m scripts.check_setup                    # valida Claude e embeddings
python -m scripts.build_index                    # indexa data/manual_colaborador.txt
python -m scripts.ask "Quantos dias de férias eu tenho?"
python -m scripts.ask_hybrid "erro E-5107" rrf   # métodos: rrf | weighted | semantic | lexical
```

---

## Funcionalidades por módulo

### `src/config.py`
Carrega o `.env` com `python-dotenv` e expõe `ANTHROPIC_API_KEY`, `HF_TOKEN`, `LLM_MODEL` e `EMBEDDING_MODEL`.

### `src/chunking.py`
Quatro estratégias de divisão de texto, para comparar na prática:

| Função | Como funciona | Parâmetros |
|---|---|---|
| `fixed_size_chunks` | Corta a cada N caracteres, com sobreposição. Simples, mas pode cortar no meio de frases. | `chunk_size=400`, `overlap=80` |
| `sentence_chunks` | Separa por sentenças (`split_sentences`), agrupa até um máximo de caracteres e repete as últimas sentenças no chunk seguinte. | `max_chars=400`, `overlap_sentences=1` |
| `recursive_chunks` | Tenta cortar pelo separador mais natural (`\n\n`, `\n`, `. `, espaço), junta pedaços pequenos vizinhos e aplica overlap pela cauda do chunk anterior, sem cortar palavras. **É a estratégia usada nos pipelines.** | `chunk_size=400`, `overlap=60` |
| `semantic_chunks` | Gera embeddings de cada sentença e corta onde a similaridade entre sentenças consecutivas cai abaixo de um percentil. Recebe o modelo como argumento. | `percentile=25` |

Os pipelines chamam `recursive_chunks` com `chunk_size=500` e `overlap=60`.

### `src/embeddings.py`
Classe `Embedder`: encapsula o `SentenceTransformer` (nome vindo de `EMBEDDING_MODEL`).
- `embed(texts, batch_size=16)`: devolve matriz `(n, dimensões)` com **vetores normalizados**, então o produto escalar equivale à similaridade de cosseno.
- `embed_one(text)`: atalho para um único texto.

### `src/vector_store.py`
Classe `VectorStore`: base vetorial local, em memória.
- `add(texts, vectors, metadata)`: acrescenta chunks, vetores e metadados (`source`, `chunk`).
- `search(query_vector, k)`: calcula `vetores @ consulta` e devolve os `k` melhores com `index`, `score`, `text` e `metadata`. É força bruta (varre todos os vetores).
- `save(dir)` / `load(dir)`: persistem em `vectors.npy` e `texts.json`.

### `src/lexical_search.py`
Busca por palavras-chave com **BM25** (`rank-bm25`).
- `tokenize`: minúsculas, tokens alfanuméricos, preserva códigos com hífen (`e-5107`, `sku-882`) e remove stopwords do português (`STOPWORDS_PT`).
- `LexicalSearch(chunks).search(query, k)`: devolve `index`, `score` e `text`.

Útil quando a pergunta contém termos exatos, como códigos de erro, que a busca semântica tende a errar.

### `src/fusion.py`
Combina os rankings semântico e léxico:
- `weighted_fusion(..., alpha=0.5)`: normaliza os scores (min-max) e faz média ponderada: `alpha * semântico + (1 - alpha) * léxico`.
- `reciprocal_rank_fusion(..., rrf_k=60)`: usa só a **posição** de cada resultado (`1 / (rrf_k + rank)`), então não depende da escala dos scores. É o método padrão.

### `src/generation.py`
Classe `Generator`: chama o Claude (`anthropic.Anthropic`).
- `SYSTEM_PROMPT`: responde em português, **só com o contexto fornecido**, cita fontes como `[1]`, `[2]`, ignora instruções que apareçam dentro do contexto (defesa contra prompt injection) e, sem resposta no contexto, devolve exatamente "Não encontrei essa informação nos documentos disponíveis.".
- `build_user_prompt`: monta `<contexto>` com `<trecho id="n">` numerados e `<pergunta>`.
- `answer(question, chunks, max_tokens=600)`: devolve o texto da resposta.

### `src/rag.py` (`RAGPipeline`)
Pipeline **somente semântico**.
- `index_file(path, chunk_size=500, overlap=60)`: lê o TXT, divide com `recursive_chunks`, gera embeddings e adiciona ao `VectorStore`.
- `save()` / `load()`: gravam e carregam o índice de `data/index`.
- `retrieve(question)`: busca os `top_k` (padrão 3) chunks mais similares.
- `ask(question)`: recupera, gera a resposta e devolve `{question, answer, sources}`.

### `src/hybrid_rag.py` (`HybridRAGPipeline`)
Pipeline **híbrido**: mantém o índice vetorial e o BM25.
- `top_k=3` chunks finais; `fetch_k=10` candidatos de cada busca antes da fusão.
- `retrieve(question, method, alpha)`: `rrf` (padrão), `weighted`, `semantic` ou `lexical`.
- `ask(question, method, alpha)`: igual ao `RAGPipeline.ask`, com o campo `method`.
- `load()` recarrega o índice vetorial e **reconstrói o BM25** a partir dos textos.

---

## Scripts

| Script | O que faz |
|---|---|
| `check_setup` | Testa a chamada ao Claude e carrega o modelo de embeddings, mostrando dimensão, dispositivo e similaridades de exemplo (carro/automóvel/bolo). |
| `build_index` | Indexa `data/manual_colaborador.txt` e salva em `data/index`. |
| `ask` | Pergunta no pipeline semântico (usa o índice salvo) e mostra resposta e fontes. |
| `ask_hybrid` | Pergunta no pipeline híbrido; o último argumento opcional escolhe o método. |
| `semantic_search` | Indexa com `sentence_chunks` e roda perguntas de exemplo, só recuperação (sem LLM). |
| `compare_chunking` | Imprime as 4 estratégias de chunking sobre o documento de exemplo, com estatísticas de tamanho. |
| `compare_search` | Compara resultados semânticos e BM25 lado a lado. |
| `compare_methods` | Compara `semantic`, `lexical`, `weighted` e `rrf` (**reindexa e sobrescreve** `data/index`). |

> `semantic_search` e `compare_methods` também regravam `data/index` com o chunking que usam. Rode `build_index` de novo para voltar ao índice padrão.

## Dados de exemplo
`data/manual_colaborador.txt` é um manual fictício ("Acme Tech") com 5 seções: férias, trabalho remoto, reembolso, suporte de TI (códigos `E-4021` e `E-5107`) e segurança. Os códigos de erro servem para mostrar onde a busca léxica ganha da semântica. O diretório `data/index/` está versionado.

---

## Limitações conhecidas

1. **Tokenizer léxico não suporta acentos**: o regex `[a-z0-9]` quebra "refeição" em "refei" e "o", o que prejudica o BM25 em português.
2. **`HybridRAGPipeline.index_file` com vários arquivos**: `self.chunks` é sobrescrito a cada arquivo, então o BM25 cobre só o último e os índices divergem.
3. **Tudo em memória, sem gestão de documentos**: sem IDs estáveis, remoção, reindexação ou deduplicação. O BM25 é reconstruído a cada `load()`.
4. **A fusão descarta `metadata`** (fonte e posição) dos resultados.
5. **`recursive_chunks`**: perde o ponto ao dividir por `". "`, o overlap é em caracteres e ignora os títulos Markdown (`##`).
6. **`split_sentences` é ingênuo**: quebra em abreviações e valores como "R$ 1.000,00.".
7. **`semantic_chunks` sem limite de tamanho**: pode gerar chunks muito grandes ou muito pequenos.
8. **Geração sem salvaguardas**: não trata contexto vazio nem aplica limiar de relevância, e lê `response.content[0].text` sem checar o tipo do bloco.
9. **Duplicação**: `rag.py` e `hybrid_rag.py` repetem a lógica, e há vários scripts de experimento.
10. **Só TXT**, com um arquivo fixo em `build_index`, e sem CLI de ingestão.
