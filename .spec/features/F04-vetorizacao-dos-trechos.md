# F04 — Vetorização dos trechos

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada |
| **Marco** | M1 — Fatia vertical |
| **Depende de** | F01 (`app_meta`, esquema) e F03 (consome `Chunk.embedding_text`) |
| **Regras de negócio** | Nenhuma diretamente (base técnica da busca semântica, F06) |
| **Seções da arquitetura** | §3 Embeddings, §6 (`app_meta`, 6.1 arquivos grandes), §8 (`check`), §14 Testes |

## 1. Objetivo
Gerar o vetor (1024 dimensões, normalizado) de cada trecho a partir do `embedding_text`, e registrar no banco qual modelo os gerou. Se o modelo configurado for diferente do registrado, a vetorização é **bloqueada** com instrução de reindexar, para nunca misturar vetores incomparáveis.

## 2. Escopo

**Inclui**
- `Embedder` melhorado: dispositivo automático (MPS ou CPU), `batch_size` configurável, `max_seq_length` explícito, carga única do modelo por processo, expõe `model_name` e `dimension`.
- `embed_chunks(embedder, chunks)`: vetoriza `Chunk`s em fluxo, em lotes, sem manter o documento inteiro em memória.
- **Aviso** (não bloqueia) quando algum trecho excede `max_seq_length` em tokens.
- Registro do modelo em `app_meta` (`embedding_model`, `embedding_dim`) na **primeira** vetorização, sem sobrescrever depois.
- Bloqueio quando o modelo configurado diverge do registrado, ou quando a dimensão do modelo difere da do esquema (1024).
- `python -m src.cli check` passa a conferir o modelo de embeddings (seção 4.2).
- Script de apoio `scripts/embed_document.py`.
- Em `src/loaders.py` (F02), `pymupdf` e `pymupdf4llm` passam a ser importados **só quando um PDF é lido** (import tardio). Não muda comportamento nem assinaturas; motivo na seção 11.

**Não inclui**
- Gravar trechos e vetores em `chunks` (F05) e o adaptador `pgvector` (F05).
- Busca por similaridade no banco (F06) e geração de resposta (F07).
- Migrar a dimensão do banco ou trocar de modelo automaticamente.
- Comando de reindexação (F05/F08). A F04 só orienta a reindexar.
- Modos esparso e multi-vetor do bge-m3.
- Tamanho definitivo dos trechos (F11).
- Migrar `rag.py`, `hybrid_rag.py` e scripts antigos (F05/F12). Eles seguem usando `embed` e `embed_one`, que continuam compatíveis.

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| — | A F04 não implementa regra de negócio diretamente. |

**Regras técnicas**
- **T1.** O texto vetorizado é `Chunk.embedding_text` (seção + conteúdo), nunca o `content` limpo.
- **T2.** Todo vetor sai normalizado (norma ≈ 1), então cosseno = produto escalar.
- **T3.** O modelo vem só de `EMBEDDING_MODEL` (`.env`). Não há nome de modelo fixo no código.
- **T4.** O modelo é carregado **uma vez por processo**.
- **T5.** `app_meta` é gravada **somente** se as chaves ainda não existem. Nunca se sobrescreve.
- **T6.** Modelo configurado ≠ registrado, ou dimensão do modelo ≠ 1024: **erro e nenhuma vetorização**. A verificação do nome ocorre **antes** de carregar o modelo.
- **T7.** Trecho acima de `max_seq_length` tokens: **aviso**, nunca bloqueio. O modelo trunca o excedente.
- **T8.** Mesma entrada produz o mesmo vetor.
- **T9.** Importar `src.embeddings` não carrega modelo nem exige `.env` ou banco.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. A pessoa (ou, a partir da F05, a ingestão) pede a vetorização dos trechos de um documento.
2. A aplicação lê `EMBEDDING_MODEL` e consulta `app_meta`:
   - sem registro: segue, e o modelo será registrado ao final da primeira carga bem-sucedida;
   - registro igual: segue;
   - registro diferente: erro (4.2).
3. Carrega o modelo uma vez e escolhe o dispositivo (MPS se disponível, senão CPU).
4. Confere a dimensão do modelo (1024). Se for outra, erro.
5. Conta os tokens de cada `embedding_text`. Se algum passar de `max_seq_length`, mostra um único aviso com a lista de `chunk_index`.
6. Vetoriza em lotes (padrão 64), entregando `(Chunk, vetor)` em fluxo.
7. Na primeira vetorização bem-sucedida, grava `embedding_model` e `embedding_dim` em `app_meta`.

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| `EMBEDDING_MODEL` não definida | Erro, sem carregar nada. Código 1. | `EMBEDDING_MODEL não definida. Copie .env.example para .env e preencha.` |
| Modelo configurado ≠ registrado | Erro **antes** de carregar o modelo. Código 1. | `O modelo de embeddings configurado ("X") é diferente do registrado no banco ("Y"). Os vetores existentes não são comparáveis. Reindexe a base ou restaure EMBEDDING_MODEL no .env.` |
| Dimensão do modelo ≠ 1024 | Erro após carregar o modelo. Código 1. | `O modelo "X" gera vetores de N dimensões, mas o banco usa 1024. Trocar de dimensão exige nova migração.` |
| Modelo não encontrado ou sem acesso (nome errado, sem rede, token inválido) | Erro claro, sem traceback. Código 1. | `Não foi possível carregar o modelo "X": <motivo curto>. Confira EMBEDDING_MODEL, a rede e o HF_TOKEN.` |
| Banco indisponível ou `app_meta` ausente | Erro (a gravação do registro é parte do fluxo). Com `--no-db` no script, o registro é pulado. | Mensagem de `DbError` da F01. |
| Trecho acima de `max_seq_length` tokens | **Aviso**, vetoriza mesmo assim. | `Aviso: N trecho(s) excedem 8192 tokens e serão truncados pelo modelo (chunk_index: 12, 40).` |
| Lista de trechos vazia | Sem erro, devolve zero vetores. O registro em `app_meta` **não** é gravado (nada foi vetorizado). | `Trechos: 0` |
| Registro já existe e é igual | Nada é gravado de novo. | — |
| Falha no meio da vetorização | `app_meta` não é gravada (só após sucesso). Nada parcial é gravado, porque a F04 não grava vetores. | Erro com a causa. |

**`check` (F01 ampliado).** Sem carregar o modelo, só comparando nomes e dimensão:

| Situação em `app_meta` | Resultado no `check` |
|---|---|
| Sem registro | Aviso: `Modelo de embeddings ainda não registrado (será gravado na primeira vetorização).` |
| Igual ao `.env` e dimensão 1024 | OK: `Modelo de embeddings: BAAI/bge-m3 (1024 dimensões)` |
| Diferente do `.env` | **Falha**: mesma mensagem do bloqueio acima. |
| `embedding_dim` registrado ≠ 1024 | **Falha**. |

### 4.3 Saída para a pessoa
```
$ python -m scripts.embed_document data/manual_colaborador.txt --show 2 --query "posso trabalhar de casa?"
Arquivo:    manual_colaborador.txt (txt, 1 página)
Modelo:     BAAI/bge-m3 | dispositivo: mps | dimensão: 1024 | max_seq_length: 8192
Registro:   gravado em app_meta (primeira vetorização)        # ou "já registrado, confere"
Trechos:    7 | tokens mín 58 · média 112 · máx 170 | acima do limite: 0
Vetores:    7 em 1,8 s (3,9 trechos/s) | norma mín 1,0000 · máx 1,0000
--- Trecho 0 | página 1 | seção: Manual do Colaborador — Acme Tech > Férias | vetor [0,0123 -0,0456 0,0789 …] ---
--- Trecho 1 | página 1 | seção: … > Trabalho remoto | vetor […] ---
Mais parecidos com a consulta (cosseno):
  0,71  trecho 3 | seção: … > Trabalho remoto
  0,42  trecho 1 | seção: … > Férias
  0,38  trecho 5 | seção: … > Reembolso
```
Em erro: mensagem em `stderr`, código 1, sem traceback.

## 5. Interface

**Comandos / opções da CLI**

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m src.cli check` (existente) | — | Passa a incluir a verificação do modelo de embeddings (4.2). |
| `python -m scripts.embed_document` | `<arquivo>` `[--max-chars N]` `[--overlap N]` `[--batch-size N]` `[--max-seq-length N]` `[--show N\|all]` `[--query TEXTO]` `[--no-db]` | Lê (F02), divide (F03), vetoriza e mostra o resumo da 4.3. `--query` lista os 3 trechos mais próximos em memória. `--no-db` não consulta nem grava `app_meta` (a checagem de dimensão continua). Código 0 se ok, 1 em erro. |

Não há comando novo em `src.cli` nem item de menu (a vetorização é interna ao `ingest`, da F05).

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/embeddings.py` | Modelo local de embeddings. | `Embedder(model_name=EMBEDDING_MODEL, batch_size=64, max_seq_length=8192)` com `model_name`, `dimension`, `device`, `embed(texts, batch_size=None) -> np.ndarray`, `embed_one(text)`, `count_tokens(texts) -> list[int]`; `embed_chunks(embedder, chunks: Iterable[Chunk], batch_size=None) -> Iterator[tuple[Chunk, np.ndarray]]` (emite o aviso de tokens); `EmbeddingError`. |
| `src/db.py` | Registro do modelo em `app_meta`. | `get_embedding_meta(conn) -> tuple[str, int] \| None`; `ensure_embedding_model(conn, model_name) -> bool` (erro se divergir; `True` se já registrado); `register_embedding_model(conn, model_name, dim)` (grava só se ausente, `INSERT … ON CONFLICT DO NOTHING`); `check_environment()` ampliado. |
| `scripts/embed_document.py` | Apoio ao teste manual (descartável; pode sair na F12). | `main()` |

Detalhes:
- `embed` e `embed_one` mantêm o comportamento atual para o código legado (`rag.py`, `hybrid_rag.py`, scripts `compare_*`).
- A ordem em `embed_document` é: checar `app_meta` e `EMBEDDING_MODEL` → carregar modelo → checar dimensão → vetorizar → registrar.
- A contagem de tokens usa o tokenizer do próprio modelo carregado.
- `src.embeddings` importa `sentence_transformers` e `torch` só dentro do construtor (T9).

## 6. Dados
**Sem mudanças no esquema** (`sql/001_init.sql` intacto). Só passam a ser usadas duas chaves de `app_meta`:

| key | value |
|---|---|
| `embedding_model` | `BAAI/bge-m3` |
| `embedding_dim` | `1024` |

## 7. Configuração
`EMBEDDING_MODEL` já existe no `.env` e no `.env.example`. Sem variáveis novas.

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | `.env` |
| `batch_size` | 64 | Constante em `src/embeddings.py`; `--batch-size` no script |
| `max_seq_length` | 8192 (limite nativo do bge-m3) | Constante em `src/embeddings.py`; `--max-seq-length` no script |
| Dimensão esperada | 1024 | `EMBEDDING_DIM` em `src/db.py` (já existe) |

## 8. Dependências externas
- Nenhum pacote novo (`sentence-transformers` e `numpy` já constam; `torch` vem com o primeiro).
- Acesso ao Hugging Face na primeira execução, para baixar o modelo (cerca de 2 GB); `HF_TOKEN` opcional.
- PostgreSQL com o esquema da F01 aplicado (`init-db`).
- Amostras existentes: `data/manual_colaborador.txt`, `data/amostras/com_texto.pdf`, `data/amostras/escaneado.pdf`, `data/amostras/grande.pdf`. Nenhuma amostra nova.

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** ambiente virtual ativo; comandos na raiz do projeto; `init-db` aplicado; `.env` com `EMBEDDING_MODEL=BAAI/bge-m3`; `app_meta` sem registro de embeddings no passo 1 (`DELETE FROM app_meta WHERE key LIKE 'embedding_%';`). A primeira execução baixa o modelo (lenta).

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | `check` sem registro | `python -m src.cli check` | Aviso "ainda não registrado". Nenhuma falha. Código 0. |
| 2 | Primeira vetorização | `python -m scripts.embed_document data/manual_colaborador.txt --show 2` | Modelo `BAAI/bge-m3`, dimensão 1024, dispositivo `mps` (ou `cpu`); `Registro: gravado`; 7 trechos (ou o nº da F03); norma ≈ 1,0000. Código 0. |
| 3 | Registro gravado | `SELECT * FROM app_meta WHERE key LIKE 'embedding_%';` | Duas linhas: `embedding_model=BAAI/bge-m3`, `embedding_dim=1024`. |
| 4 | Não sobrescreve | Repetir o passo 2 | `Registro: já registrado, confere`. As linhas de `app_meta` não mudam (conferir com a consulta do passo 3). |
| 5 | `check` com registro | `python -m src.cli check` | OK: `Modelo de embeddings: BAAI/bge-m3 (1024 dimensões)`. |
| 6 | Texto de embedding com seção | Ver o resumo do passo 2 (opção `--show`) | O vetor é calculado sobre `seção + conteúdo`. Conferir também pelo passo 8: a consulta "trabalhar de casa" aponta a seção de trabalho remoto. |
| 7 | Normalização | Linha `Vetores:` do passo 2 | `norma mín` e `norma máx` ≈ 1,0000. |
| 8 | Similaridade faz sentido | `python -m scripts.embed_document data/manual_colaborador.txt --query "posso trabalhar de casa?" --show 0` | O trecho de trabalho remoto aparece em 1º, com cosseno bem acima dos demais. |
| 9 | Código exato | `--query "E-5107"` | O trecho que cita E-5107 aparece entre os 3 primeiros (a busca exata completa é da F06). |
| 10 | PDF | `python -m scripts.embed_document data/amostras/com_texto.pdf --show 1` | Roda sem erro; trechos de várias páginas vetorizados; código 0. |
| 11 | Aviso de limite de tokens | `python -m scripts.embed_document data/manual_colaborador.txt --max-seq-length 32 --show 0` | Aviso `N trecho(s) excedem 32 tokens e serão truncados (chunk_index: …)`. **Não bloqueia**; vetoriza tudo; código 0. |
| 12 | Sem aviso no normal | Passo 2 | `acima do limite: 0`, sem aviso. |
| 13 | Lote | `--batch-size 4` e `--batch-size 64` no passo 2 | Mesmo resultado, vetores iguais em quantidade e norma. |
| 14 | Bloqueio por modelo diferente | `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 python -m scripts.embed_document data/manual_colaborador.txt; echo $?` | Mensagem de modelo diferente do registrado; **sem baixar nem carregar** o outro modelo; código 1; sem traceback. |
| 15 | `check` com modelo diferente | `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 python -m src.cli check; echo $?` | **Falha** com a mesma mensagem; código 1. |
| 16 | Dimensão diferente | `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 python -m scripts.embed_document data/manual_colaborador.txt --no-db; echo $?` | Erro "gera vetores de 384 dimensões, mas o banco usa 1024"; código 1. |
| 17 | Modelo inexistente | `EMBEDDING_MODEL=nao/existe python -m scripts.embed_document data/manual_colaborador.txt --no-db; echo $?` | Mensagem "Não foi possível carregar o modelo…"; código 1; sem traceback. |
| 18 | `EMBEDDING_MODEL` ausente | `EMBEDDING_MODEL= python -m scripts.embed_document data/manual_colaborador.txt; echo $?` | `EMBEDDING_MODEL não definida…`; código 1. |
| 19 | `--no-db` | `python -m scripts.embed_document data/manual_colaborador.txt --no-db` | Roda sem consultar nem gravar `app_meta`; `Registro: ignorado (--no-db)`. |
| 20 | Erro de leitura | `python -m scripts.embed_document data/amostras/escaneado.pdf; echo $?` | Mensagem da F02 (PDF sem texto); código 1; nada gravado em `app_meta`. |
| 21 | Fluxo e memória | `/usr/bin/time -l python -m scripts.embed_document data/amostras/grande.pdf --show 0` | Termina sem erro; anotar tempo, trechos/s e pico de memória (sem crescer proporcional às páginas além do modelo). |
| 22 | Carga única | Ler a saída do passo 21 (e do código) | O modelo é carregado uma única vez por execução. |
| 23 | Importação sem efeitos | `python -c "from src.embeddings import Embedder, embed_chunks"` | Sem saída, sem erro, sem `.env`, sem banco, sem carregar modelo. |
| 24 | Compatibilidade legada | `python -c "import src.rag, src.hybrid_rag"` | Sem erro. |
| 25 | Somente o previsto | `git status` ao final | Só os arquivos previstos (código, script, docs). Nada em `data/` além do já existente. |

**Consultas úteis para conferir o banco**
```sql
SELECT key, value FROM app_meta WHERE key LIKE 'embedding_%' ORDER BY key;
DELETE FROM app_meta WHERE key LIKE 'embedding_%';   -- apenas para repetir o passo 1/2
```

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F01 | `python -m src.cli init-db` e `check` (do roteiro da F01) | `check` foi alterado e `app_meta` passa a ter linhas. |
| F02 | 1 | Leitura segue intacta (a F04 só consome). |
| F03 | 1, 8, 14, 25 | `Chunk`/`chunk_pages` são consumidos, sem alteração. |
| Código atual (`rag.py`, `hybrid_rag.py`, `scripts/compare_*.py`, `semantic_search.py`) | `python -c "import src.rag, src.hybrid_rag"` e `python -m scripts.compare_chunking` | Usam `Embedder.embed`/`embed_one`, cujo contrato foi preservado. |
| F05, F06, F11 | — | Passam a consumir `Embedder` e `embed_chunks`. Mudança futura exige repetir os passos 2, 4, 14 e 16. |

## 11. Riscos e decisões

**Decisões tomadas** (com o motivo)
- **Tokens: só aviso** (decisão da pessoa): 900 caracteres têm folga ampla frente aos 8192 tokens. Medição fina fica na F11.
- **Registro na primeira vetorização, sem sobrescrever** (decisão da pessoa): trocar de modelo exige reindexar, então a chave não deve mudar sozinha.
- **Divergência bloqueia** (decisão da pessoa): evita misturar vetores incompatíveis no banco.
- **`pgvector` só na F05** (decisão da pessoa): `app_meta` é texto puro e dispensa o adaptador.
- **`check` não carrega o modelo**: compara só nomes e dimensão registrados. Fica rápido e não baixa 2 GB só para verificar o ambiente.
- **`max_seq_length` = 8192**: é o limite nativo do bge-m3. Valor menor truncaria trechos grandes sem necessidade. Revisável na F11.
- **Verificação do nome antes de carregar o modelo**: falha rápida e sem downloads inúteis.
- **Registro só após sucesso**: uma execução que falha não deixa o modelo registrado.
- **`--query` e `--max-seq-length` no script**: servem para testar similaridade e o aviso. A busca de verdade é da F06.
- **`embed`/`embed_one` preservados**: o código legado segue funcionando até a F12.
- **Import tardio de `pymupdf`/`pymupdf4llm` em `src/loaders.py`** (investigação do código 134): carregar essas bibliotecas antes do torch/MPS fazia o processo terminar com `libc++abi: recursive_mutex lock failed` (código 134) em ~15% das execuções, depois de imprimir o resultado. Medido: `embed_document --no-db` com TXT, 8/50 antes e 0/50 depois; com PDF, 0/40 depois. Não é prova de causa única (ver pontos em aberto).
- **Risco aceito:** `app_meta` guarda o nome, não um hash dos pesos. Se o mesmo nome apontar para uma revisão diferente do modelo, não detectamos.
- **Risco aceito:** no Mac, o MPS pode se comportar de forma diferente da CPU em alguns ambientes (tempo e pequenas diferenças numéricas). Se aparecer problema, o fallback é CPU.

**Pontos em aberto**
- Uma execução do experimento de investigação saiu com **código 1** (não 134), sem `stderr` guardado. Não foi explicada nem reproduzida depois da correção.
- Qual import causa o conflito (`pymupdf`, `pymupdf4llm` ou a ordem de carga com o torch) não foi isolado. No PDF o MuPDF é carregado antes do modelo (em `inspect_document`) e não houve falha em 40 execuções, o que sugere que `pymupdf4llm` antes do torch pesa mais, mas não foi testado.
- Se a F05 (ingestão em lote, misturando PDFs e vetorização no mesmo processo) voltar a mostrar o código 134, reabrir a investigação.

## 12. Documentação a atualizar
- `.spec/ROADMAP.md`: status da F04 e coluna "Depende de" (F01, F03).
- `.spec/ARQUITETURA.md` §3 e §8: registrar `embed_chunks`, o aviso de tokens e o `check` ampliado.
- `.claude/CLAUDE.md`: acrescentar F04 ao "implementada e verificada" quando concluída.
- `.env.example` e `README.md`: sem mudanças (README na F12).

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
| 2026-10-03 | Claude (pré-verificação na implementação) | Passos 1–5, 7–20, 23–25 executados sem falhas de comportamento; passos 6, 21 e 22 verificados em parte (ver observações) | Aguarda execução e aprovação da pessoa. Passo 21 (`grande.pdf`, 36 páginas, 143 trechos): 24,8 s (5,8 trechos/s), pico de memória ~1,4 GB (modelo incluído). Passo 8: "trabalhar de casa" → trecho de Trabalho remoto em 1º (0,56 contra 0,44). Passo 9: "E-5107" → trecho de Suporte de TI em 1º (0,42). Passo 11: aviso listou os 5 trechos; o `transformers` também imprime a sua própria mensagem sobre o limite. **Observação aberta:** em 1 de 13 execuções com `--no-db` o processo imprimiu tudo e terminou com código 134 (`libc++abi: recursive_mutex lock failed`, no encerramento do interpreter, provável corrida do torch/MPS ao sair). Não reproduzido nas demais. |
| 2026-10-03 | Claude (investigação do código 134) | Reproduzido e mitigado | Script mínimo (torch + `SentenceTransformer`): 0/120. `embed_document --no-db` completo: 8/50 (16%), sempre a mesma mensagem. Script mínimo + `import pymupdf, pymupdf4llm` antes do torch: 6/40 (uma delas com código 1, não explicada); + tokenizer: 0/40; + numpy: 0/40. Após o import tardio em `src/loaders.py`: TXT 0/50, PDF 0/40. Regressão da F02 (`read_document` em TXT, PDFs com texto/parcial/escaneado/corrompido/protegido, .docx, vazio) com as mesmas saídas e códigos; `chunk_document` ok. |
| 2026-10-03 | Jose Julio | Aprovado | Roteiro da seção 9 e alteração em `src/loaders.py` (import tardio) aprovados, conforme relato da pessoa. Pontos em aberto da seção 11 (código 1 não explicado; import exato causador) seguem registrados para reabrir se reaparecerem. |
