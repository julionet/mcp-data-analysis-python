# F05 — Cadastro de documento

> **Atualização (F13):** `ingest` também aceita `.md` (gravado com `file_type = 'md'`). Detalhes em `F13-suporte-a-markdown.md`.
> **Atualização (F06):** a decisão "`tsv` só com `content`" foi revogada: a migração 003 gera `tsv` e `tsv_en` a partir de seção + conteúdo. O cadastro não muda (colunas geradas pelo banco).

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada |
| **Marco** | M1 — Fatia vertical |
| **Depende de** | F01 (esquema, `connect`), F02 (`inspect_document`, `iter_pages`), F03 (`chunk_pages`), F04 (`Embedder`, `embed_chunks`, registro do modelo) |
| **Regras de negócio** | R4, R9 (R7 e R8 valem para o arquivo cadastrado; o resumo por pasta é da F08) |
| **Seções da arquitetura** | §4 Ingestão, §6 (esquema, 6.1 arquivos grandes, camada de acesso), §8 (`ingest`), §14 Testes |

## 1. Objetivo
Cadastrar **um arquivo** TXT ou PDF na base: ler, dividir, vetorizar e gravar o documento e seus trechos no PostgreSQL **numa única transação**. Conteúdo já cadastrado é ignorado (informando de qual arquivo é cópia), e arquivos grandes mostram progresso. É o primeiro passo em que a base passa a conter dados reais, e destrava a busca (F06) e a resposta (F07).

## 2. Escopo

**Inclui**
- Comando `ingest <arquivo>` na CLI (`python -m src.cli ingest`).
- Camada de acesso `src/repository.py` (SQL explícito, sem ORM) e `src/ingestion.py` (orquestra o fluxo).
- Cadastro de **um arquivo avulso** (`documents.source_id = NULL`).
- Detecção de duplicados por `sha256` (R4) e de arquivo já cadastrado no mesmo caminho.
- Gravação atômica do documento e dos trechos (R9), em lote.
- Progresso visível durante a leitura/vetorização, em `stderr`.
- Registro do modelo de embeddings em `app_meta` após o primeiro cadastro bem-sucedido (reuso da F04).
- Adaptador `pgvector` para gravar o vetor.

**Não inclui** (fica para outra feature ou fora de escopo)
- Pastas, tabela `sources`, `--recursive`, `--prune`, `--force` e resumo de vários arquivos (F08).
- Substituir um arquivo **alterado** no mesmo caminho (F08; decisão da seção 11).
- Listar e remover documentos (F09), busca (F06), resposta (F07).
- Limites de tamanho de arquivo e de páginas (decidido: sem limite agora; medir antes).
- Retomar um cadastro interrompido no meio (não há estado parcial: ver decisão na seção 11).
- Item de menu (F10).

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R4 | Um arquivo com o mesmo `sha256` de um documento já cadastrado **não é cadastrado de novo**. A saída informa o caminho do original. Vale também para o mesmo caminho sem mudanças. |
| R7 | Arquivo corrompido, sem texto ou de formato não aceito gera erro claro, **nada é gravado** e o código de saída é 1. (A continuação entre vários arquivos é da F08.) |
| R8 | PDF sem texto selecionável é rejeitado (mensagem da F02). |
| R9 | O documento só existe na base depois de cadastrado por completo. Falha ou interrupção (Ctrl+C) em qualquer ponto não deixa documento nem trechos. |

**Regras técnicas**
- **T1.** Documento e trechos são gravados em **uma transação**, só depois que todos os vetores foram gerados. Nenhuma transação fica aberta durante a vetorização.
- **T2.** Antes de carregar o modelo (lento), o fluxo confere duplicado e `EMBEDDING_MODEL` x `app_meta` (reuso de `ensure_embedding_model`).
- **T3.** O índice único `documents_sha256_uniq` é a garantia final contra duplicado: se duas execuções cadastram o mesmo conteúdo ao mesmo tempo, uma grava e a outra é tratada como duplicada, sem erro.
- **T4.** Um trecho é gravado com `content` limpo, `page`, `section`, `chunk_index` e o vetor de `embedding_text` (F04, T1). A coluna `tsv` é gerada pelo banco.
- **T5.** O caminho gravado em `source_path` é **absoluto e resolvido** (`Path.resolve()`).
- **T6.** Importar `src.ingestion` ou `src.repository` não carrega o modelo, não conecta ao banco e não exige `.env`.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. A pessoa executa `python -m src.cli ingest <arquivo>`.
2. A aplicação valida o arquivo (`inspect_document`): extensão, leitura, PDF com texto, `sha256`, nº de páginas.
3. Conecta ao banco e consulta:
   - mesmo `sha256` já cadastrado → termina informando duplicado (4.2);
   - mesmo caminho com outro `sha256` → termina com aviso (4.2);
   - caso contrário segue.
4. Confere o modelo de embeddings contra `app_meta` (F04) e só então carrega o modelo.
5. Lê as páginas em fluxo, divide (`chunk_pages`, estratégia `structured`), vetoriza em lotes e acumula os pares (trecho, vetor), mostrando o progresso.
6. Abre uma transação: grava o `documents` (`status='indexed'`) e todos os `chunks` em lote; confirma.
7. Se for a primeira vetorização da base, registra o modelo em `app_meta` (F04).
8. Mostra o resumo (4.3). Código 0.

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| Arquivo novo | Cadastra (4.1). | Resumo `Cadastrado` |
| Mesmo conteúdo, mesmo caminho | Nada é feito. Código 0. | `Já cadastrado, sem mudanças: <caminho>` |
| Mesmo conteúdo em **outro** caminho | Ignorado, sem trechos novos (R4). Código 0. | `Duplicado de <caminho do original>. Nada foi cadastrado.` |
| Mesmo caminho, conteúdo diferente | Nada é feito. Código 1. (Substituição fica para a F08, decisão da seção 11.) | `O arquivo <caminho> mudou desde o cadastro. A atualização de arquivos alterados ainda não existe.` |
| Arquivo inexistente, formato não aceito, corrompido, sem texto | Erro da F02, nada gravado. Código 1. | Mensagem da F02 |
| Argumento é uma pasta | Erro. Código 1. | `<caminho> é uma pasta. O cadastro de pastas será oferecido na F08; informe um arquivo.` |
| Arquivo sem nenhum trecho após dividir | Erro, nada gravado. Código 1. | `Nenhum trecho gerado a partir de <arquivo>.` |
| `EMBEDDING_MODEL` ausente, divergente do registrado, dimensão ≠ 1024, modelo não carregou | Erros da F04, **antes** de qualquer gravação. Código 1. | Mensagens da F04 |
| Banco indisponível ou esquema ausente | Erro, nada gravado. Código 1. | Mensagem de `DbError` da F01 (`Execute init-db.`) |
| Falha ou Ctrl+C durante leitura/vetorização | Nada gravado (T1). Código 1 (2 no Ctrl+C não é exigido). | `Cadastro interrompido; nada foi gravado.` |
| Falha na gravação (transação) | Rollback completo. Código 1. | `Erro ao gravar o documento (nada foi gravado): <motivo curto>` |
| Duas execuções simultâneas do mesmo conteúdo | Uma grava; a outra detecta a violação do índice único e responde como duplicado (T3). | `Duplicado de <caminho>…` |
| Mesmo conteúdo cadastrado antes por outro caminho que **já não existe** em disco | Continua duplicado (a base não verifica o disco). | `Duplicado de <caminho>…` |

### 4.3 Saída para a pessoa
Progresso em `stderr` (linha reescrita no terminal; fora de terminal, uma linha a cada ~10%):
```
Lendo e vetorizando: página 120/500 | trechos 640 | 4,1 trechos/s | restante ~7 min
```
Resumo em `stdout`:
```
$ python -m src.cli ingest data/manual_colaborador.txt
Arquivo:    /Users/.../data/manual_colaborador.txt (txt, 1 página)
Resultado:  cadastrado
Documento:  id 1 | 7 trechos | páginas 1–1
Modelo:     BAAI/bge-m3 (registrado em app_meta)      # ou "confere com o registro"
Tempo:      2,3 s

$ python -m src.cli ingest data/manual_colaborador_copia.txt
Arquivo:    /Users/.../data/manual_colaborador_copia.txt (txt, 1 página)
Resultado:  duplicado de /Users/.../data/manual_colaborador.txt (nada cadastrado)
```
Erros: mensagem em `stderr`, código 1, sem traceback.

## 5. Interface

**Comandos / opções da CLI** (e item de menu, se houver)

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `python -m src.cli ingest` | `<arquivo>` | Cadastra um TXT ou PDF (4.1). Código 0 em cadastrado, já cadastrado e duplicado; 1 em erro. |

Sem opções nesta feature (`--recursive`, `--force`, `--prune` entram na F08). Sem item de menu (F10).

**Módulos e funções** (assinaturas principais, entradas e saídas)

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/repository.py` | SQL do cadastro, sem regra de negócio. | `find_by_sha256(conn, sha256) -> DocumentRow \| None`; `find_by_path(conn, path) -> DocumentRow \| None`; `add_document(conn, info, source_path, chunks_with_vectors) -> int` (uma transação: `documents` + `chunks` em lote; devolve o id; levanta `DuplicateContent` se o índice único disparar); `DocumentRow(id, source_path, sha256, status, pages)`; `DuplicateContent`. |
| `src/ingestion.py` | Orquestra o fluxo 4.1. | `ingest_file(path, progress=None) -> IngestResult` (`IngestResult(outcome, document_id, chunk_count, duplicate_of, elapsed, model_registered)`); `IngestError` (mensagem pronta). |
| `src/db.py` | Conexão e adaptador de vetor. | Ao conectar, registrar o adaptador `pgvector` (`register_vector`). Resto inalterado. |
| `src/cli.py` | Subcomando `ingest`, formatação do resumo e do progresso. | `cmd_ingest(args)` |

Detalhes:
- `ingest_file` não imprime; recebe um `progress(done_pages, total_pages, chunks, rate)` opcional e devolve o resultado para a CLI formatar.
- O progresso usa `DocumentInfo.page_count` (já conhecido) como total.
- A gravação usa `cursor.executemany` ou `COPY` em lote (decisão de implementação, a medir com `grande.pdf`).
- `outcome` ∈ `created`, `unchanged`, `duplicate`.

## 6. Dados
**Sem mudanças no esquema** (`sql/001_init.sql` intacto). Uso das tabelas existentes:

| Tabela | O que a F05 grava |
|---|---|
| `documents` | `source_id = NULL`, `source_path` (absoluto), `filename`, `file_type`, `sha256`, `pages`, `status = 'indexed'`, `error = NULL`. |
| `chunks` | `document_id`, `chunk_index`, `page`, `section`, `content`, `embedding` (1024). |
| `app_meta` | `embedding_model`, `embedding_dim` na primeira vez (F04). |

`status` `indexing` e `failed` continuam no esquema, mas a F05 **não os usa**: como a gravação é uma única transação, nunca existe documento parcial (R9). Podem ser aproveitados pela F08.

## 7. Configuração
Sem variáveis novas. Requer `DATABASE_URL` e `EMBEDDING_MODEL` no `.env`.

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| Estratégia de divisão | `structured`, `MAX_CHARS` e `OVERLAP_CHARS` de `src/chunking.py` | Constantes (definição final na F11) |
| Tamanho do lote de vetorização | 64 | `BATCH_SIZE` de `src/embeddings.py` |
| Limite de tamanho de arquivo / de páginas | Sem limite | Decisão da seção 11 (medir nos passos 14 e 15) |

## 8. Dependências externas
- Pacote novo em `requirements.txt`: **`pgvector`** (adaptador do tipo `vector` para o psycopg).
- `psycopg_pool` **não** entra (decisão na seção 11).
- PostgreSQL com o esquema da F01 aplicado (`init-db`) e extensão `vector`.
- Amostras existentes: `data/manual_colaborador.txt`, `data/amostras/com_texto.pdf`, `escaneado.pdf`, `corrompido.pdf`, `grande.pdf`, `nota.docx`. **Amostra nova (a criar para o teste):** uma cópia byte a byte de `manual_colaborador.txt` em outro caminho (feita no próprio roteiro, passo 5).

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** ambiente virtual ativo; comandos na raiz do projeto; `init-db` aplicado; `.env` completo; tabelas `documents` e `chunks` vazias e `app_meta` sem registro de embeddings (`DELETE FROM documents; DELETE FROM app_meta WHERE key LIKE 'embedding_%';`). A cópia usada no passo 5 fica em um diretório temporário (fora do repositório).

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | Cadastro de TXT | `python -m src.cli ingest data/manual_colaborador.txt; echo $?` | `Resultado: cadastrado`, 7 trechos (ou o nº da F03), modelo registrado; código 0. |
| 2 | Dados gravados | Consultas 1–3 da seção "úteis" | 1 documento (`txt`, `indexed`, caminho absoluto); trechos com `chunk_index` de 0 a N−1, `page`, `section` e `embedding` de 1024 dimensões; `app_meta` com as duas linhas. |
| 3 | Mesmo arquivo de novo | Repetir o passo 1 | `Já cadastrado, sem mudanças`; código 0; contagens do passo 2 iguais. |
| 4 | Caminho relativo e absoluto | `python -m src.cli ingest ./data/../data/manual_colaborador.txt` | Também `Já cadastrado` (T5), sem segundo documento. |
| 5 | Duplicado em outro caminho | `cp data/manual_colaborador.txt /tmp/copia.txt && python -m src.cli ingest /tmp/copia.txt; echo $?` | `Duplicado de …/data/manual_colaborador.txt`; **nenhum** documento ou trecho novo; código 0. (R4) |
| 6 | Cadastro de PDF | `python -m src.cli ingest data/amostras/com_texto.pdf` | Cadastrado; trechos de várias páginas, com `page` correta; seções preenchidas quando houver títulos. |
| 7 | Página e seção por trecho | Consulta 4 | Páginas de 1 ao nº de páginas do PDF; nenhum `page` fora do intervalo; `content` sem o prefixo de seção. |
| 8 | PDF sem texto | `python -m src.cli ingest data/amostras/escaneado.pdf; echo $?` | Mensagem da F02 (R8); código 1; **nada** gravado (contagens inalteradas). |
| 9 | PDF corrompido | `… ingest data/amostras/corrompido.pdf; echo $?` | Mensagem da F02; código 1; nada gravado. |
| 10 | Formato não aceito | `… ingest data/amostras/nota.docx; echo $?` | Mensagem da F02; código 1. |
| 11 | Arquivo inexistente | `… ingest data/nao_existe.txt; echo $?` | Mensagem da F02; código 1. |
| 12 | Pasta | `… ingest data/amostras; echo $?` | Mensagem "é uma pasta… F08"; código 1; nada gravado. |
| 13 | Arquivo alterado no mesmo caminho | `cp data/amostras/sem_titulos.txt /tmp/y.txt`, cadastrar `/tmp/y.txt`, depois `echo "linha nova" >> /tmp/y.txt` e cadastrar de novo | Segunda vez: mensagem "mudou desde o cadastro"; código 1; o cadastro original permanece intacto. |
| 14 | Arquivo grande e progresso | `/usr/bin/time -l python -m src.cli ingest data/amostras/grande.pdf` | Linha de progresso avança até o fim; cadastrado; anotar tempo, trechos/s e pico de memória (sem crescer proporcional às páginas além do modelo). |
| 15 | Atomicidade: interrupção | Iniciar o passo 14 (com `grande.pdf` ainda não cadastrado) e interromper com Ctrl+C antes de terminar | `Cadastro interrompido; nada foi gravado.`; o documento **não** existe em `documents`, nem trechos órfãos em `chunks` (Consulta 5 = 0 órfãos; R9). |
| 16 | Atomicidade: falha na gravação | Provocar falha após a vetorização (ex.: temporariamente renomear a tabela `chunks` em um banco de teste, ou derrubar a conexão) | Rollback completo: nenhum documento e nenhum trecho do arquivo; mensagem de erro; código 1. Descrever como foi provocado no registro. |
| 17 | Concorrência | Em dois terminais, `ingest` do **mesmo** arquivo novo ao mesmo tempo | Um `cadastrado`, o outro `duplicado` (ou `já cadastrado`); 1 documento e um só conjunto de trechos; sem traceback. (T3) |
| 18 | Modelo divergente | `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 python -m src.cli ingest <arquivo novo>; echo $?` | Mensagem da F04; **sem baixar nem carregar** o modelo; código 1; nada gravado. |
| 19 | Banco sem esquema | Apontar para um banco sem tabelas, ou renomear temporariamente `documents` | Erro claro (`Execute init-db`); código 1; sem traceback. |
| 20 | Sem efeitos na importação | `python -c "import src.ingestion, src.repository"` | Sem saída, sem erro; sem carregar modelo nem conectar. |
| 21 | Regressão da CLI | `python -m src.cli check` e `python -m src.cli init-db` | Sem falhas; `check` mostra o modelo registrado. |
| 22 | Somente o previsto | `git status` ao final | Só os arquivos previstos (código, `requirements.txt`, docs). Nada novo em `data/`. |

**Consultas úteis para conferir o banco**
```sql
-- 1) documentos
SELECT id, source_path, file_type, sha256, pages, status, source_id FROM documents ORDER BY id;
-- 2) trechos por documento
SELECT document_id, count(*), min(chunk_index), max(chunk_index), min(page), max(page) FROM chunks GROUP BY document_id;
-- 3) dimensão e metadados dos vetores
SELECT chunk_index, page, section, vector_dims(embedding) FROM chunks WHERE document_id = 1 ORDER BY chunk_index LIMIT 5;
SELECT key, value FROM app_meta WHERE key LIKE 'embedding_%' ORDER BY key;
-- 4) intervalo de páginas
SELECT d.source_path, d.pages, max(c.page) FROM documents d JOIN chunks c ON c.document_id = d.id GROUP BY d.id;
-- 5) trechos órfãos / documentos sem trechos (devem ser 0)
SELECT count(*) FROM chunks c LEFT JOIN documents d ON d.id = c.document_id WHERE d.id IS NULL;
SELECT count(*) FROM documents d LEFT JOIN chunks c ON c.document_id = d.id WHERE c.id IS NULL;
-- repetir o roteiro
DELETE FROM documents;  -- apaga os trechos em cascata
DELETE FROM app_meta WHERE key LIKE 'embedding_%';
```

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| F01 | `init-db` e `check` | `db.connect` passa a registrar o adaptador `pgvector`. |
| F02 | 1 | Só consumida. |
| F03 | 1, 8 | `chunk_pages` só consumida. |
| F04 | 2, 4, 14, 16 | Reuso de `Embedder`, `embed_chunks` e do registro em `app_meta`. Confirmar também que o código 134 (ponto em aberto da F04) **não** reaparece ao cadastrar PDFs e TXT no mesmo processo (passos 1, 6 e 14 daqui, várias vezes). |
| Código atual (`rag.py`, `hybrid_rag.py`) | `python -c "import src.rag, src.hybrid_rag"` | `src/db.py` e `requirements.txt` mudam; o legado não deve quebrar. |
| F06, F08, F09 | — | Passam a depender de `repository.py` e da forma como o documento é gravado. |

## 11. Riscos e decisões

**Decisões tomadas** (confirmadas pela pessoa)
- **Arquivo alterado no mesmo caminho: só avisar** (código 1). A substituição fica para a F08 (R5).
- **Sem limite de tamanho de arquivo nem de páginas na F05.** Os passos 14 e 15 medem tempo e memória; o limite será decidido depois, com os números.
- **Um arquivo por vez nesta feature.** Pastas, `sources` e resumo em lote são da F08 (ROADMAP). Mantém a spec curta e verificável.
- **Gravação única ao final, não por lote.** O ROADMAP e a ARQUITETURA pedem uma transação para documento e trechos. Os vetores de um PDF de 500 páginas ocupam ~10 MB (2.500 × 1024 × 4 bytes); manter só eles em memória é aceitável, e evita transação aberta por minutos e estados parciais. Em troca, **não há retomada**: uma interrupção refaz tudo (aceito).
- **`status` `indexing`/`failed` sem uso na F05.** Não há documento parcial para marcar.
- **Duplicado como sucesso (código 0), "mudou" como erro (código 1).** Duplicado é resultado esperado de R4; arquivo alterado deixa o cadastro desatualizado e precisa chamar a atenção.
- **`psycopg_pool` fica de fora.** A CLI abre uma conexão por execução. O pool só faz sentido com API/web (futuro). O ROADMAP e a ARQUITETURA previam `psycopg_pool` em F05/F06; o adiamento foi confirmado.
- **Concorrência mínima na F05 via índice único (T3).** A proteção contra duas pessoas atualizando a **mesma pasta** (decisão pendente do ROADMAP) é da F08.
- **`source_id = NULL`** para arquivo avulso, como prevê o esquema.
- **Caminho resolvido (T5).** Evita duplicar o mesmo arquivo por caminhos relativos diferentes.
- **Duplicado de arquivo que sumiu do disco continua duplicado** até a remoção do original (F09) ou `--prune` (F08). A base não confere o disco (R6, ARQUITETURA §4).
- **Progresso fora de terminal:** uma linha a cada ~10% das páginas. No terminal, a linha é reescrita.
- **`tsv` só com `content`**, como no esquema da F01. A F06 mede e, se faltar, altera o esquema com evidência.

**Pontos em aberto**
Nenhum.

## 12. Documentação a atualizar
- `.spec/ROADMAP.md`: status da F05.
- `.spec/ARQUITETURA.md` §4 e §8: `ingest <arquivo>` nesta fase (pasta na F08); `psycopg_pool` adiado; `src/ingestion.py` na estrutura alvo.
- `.claude/CLAUDE.md`: acrescentar F05 ao "implementada e verificada" ao concluir.
- `requirements.txt`: `pgvector`.
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
| 2026-10-09 | Claude (pré-verificação na implementação) | Passos 1–15, 17–22 executados sem falhas; 16 e parte do 17 simulados (ver observações) | Aguarda execução e aprovação da pessoa. Passo 14 (`grande.pdf`, 36 páginas, 143 trechos): 25,6 s (5,5 trechos/s), pico de memória ~1,4 GB (modelo incluído). Passo 15: SIGINT enviado após 9 s → `Cadastro interrompido; nada foi gravado.`, código 1, contagens do banco inalteradas, 0 órfãos. **Passo 16** simulado chamando `repository.add_document` com um vetor de dimensão errada no 2º trecho: rollback completo (documento e trechos). **Passo 17:** corrida real de 2 processos no mesmo arquivo: um `cadastrado`, outro `já cadastrado`; o ramo do índice único (T3) foi exercitado direto em `add_document` (`DuplicateContent`, nada gravado). Regressão: `check`, `init-db`, `import src.rag, src.hybrid_rag`, `embed_document --no-db` e `chunk_document` ok; 8 cadastros seguidos de TXT novos sem código 134. Dados de teste removidos do banco ao final (`documents` vazia; registro de `app_meta` apagado, será regravado no próximo cadastro). |
| 2026-10-09 | Jose Julio | Aprovado | Roteiro da seção 9 aprovado, conforme relato da pessoa. |
