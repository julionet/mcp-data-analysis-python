# F01 — Ambiente e banco de dados

> **Atualização (F13):** `init-db` passou a aplicar todas as migrações `sql/NNN_*.sql` em ordem (a `002` acrescenta `md` ao CHECK de `documents.file_type`) e `check` confere essa restrição. Detalhes em `F13-suporte-a-markdown.md`.
> **Atualização (F06):** a migração `003` recria `tsv` (seção + conteúdo, português) e cria `tsv_en` e `chunks_tsv_en_gin`; `check` confere a coluna e o índice. Detalhes em `F06-busca-de-trechos.md`.

| Campo | Valor |
|---|---|
| **Status da spec** | Aprovada |
| **Status da implementação** | Verificada |
| **Marco** | M1 — Fatia vertical |
| **Depende de** | Nenhuma |
| **Regras de negócio** | Nenhuma diretamente. Esta feature cria a base para R4 (duplicados) e R9 (cadastro completo). |
| **Seções da arquitetura** | §6 PostgreSQL + pgvector, §8 CLI (`init-db`, `check`), §9 Configuração, §14 Testes |

## 1. Objetivo
Deixar o ambiente pronto para as demais features: banco `rag_training_db` com a extensão vetorial ativa, esquema aplicado, configuração de acesso por `.env` e um comando que verifica se tudo está correto.

## 2. Escopo

**Inclui**
- Script SQL de preparação, executado **uma vez** por quem administra o Postgres, que cria o usuário `rag_user`, o banco `rag_training_db` e a extensão `vector`.
- Esquema completo da ARQUITETURA §6 (`sources`, `documents`, `chunks`, `app_meta`, com índices), aplicado por `init-db` de forma idempotente.
- Variável `DATABASE_URL` no `.env` e no `.env.example` (com placeholder de senha).
- Primeira versão da CLI `python -m src.cli`, com os comandos `init-db` e `check`.
- Conexão com o banco usando `psycopg` 3.

**Não inclui**
- Gravar o modelo de embeddings em `app_meta`: isso é da **F04**. Nesta feature a tabela só é criada, vazia.
- Verificar Claude e embeddings no `check`: embeddings entram na **F04** e o Claude na **F07**. Até lá, vale `scripts/check_setup.py`.
- Leitura, divisão e cadastro de documentos (F02, F03, F05) e buscas (F06).
- Menu interativo e demais comandos da CLI (F10).
- Pool de conexões e adaptador `pgvector` do Python: entram quando forem usados (F05/F06).
- Decisão sobre busca em português e inglês (F06). A coluna `tsv` segue a ARQUITETURA e pode virar uma migração depois.

## 3. Regras de negócio aplicáveis

| Regra | O que significa nesta feature |
|---|---|
| R4 | O esquema garante, no banco, que o mesmo conteúdo não entra duas vezes (índice único em `documents.sha256`). |
| R9 | `documents.status` (`indexing`, `indexed`, `failed`) existe desde já, para que um cadastro incompleto não apareça nas buscas. |

**Regras técnicas desta feature**
- **T1.** A aplicação **nunca** usa credencial de superusuário. Só o script de preparação, rodado manualmente, exige superusuário.
- **T2.** A **senha nunca** é gravada em arquivo versionado, nem aparece em saídas ou mensagens de erro da CLI. Ela fica só no `.env`.
- **T3.** `init-db` e o script de preparação são **idempotentes**: repetir não dá erro nem apaga dados.

## 4. Comportamento esperado

### 4.1 Fluxo principal
1. Quem administra o Postgres roda o script de preparação, informando a senha de `rag_user` por parâmetro.
2. A pessoa define `DATABASE_URL` no `.env`.
3. Roda `python -m src.cli init-db`. A aplicação confere a conexão e a extensão `vector`, aplica `sql/001_init.sql` em uma transação e informa o que foi criado.
4. Roda `python -m src.cli check` e vê o resultado de cada item. Se tudo estiver certo, o comando termina com código 0.

### 4.2 Fluxos alternativos e erros

| Situação | Comportamento esperado | Mensagem / saída |
|---|---|---|
| `DATABASE_URL` ausente | Não tenta conectar. Código de saída 1. | `DATABASE_URL não definida. Copie .env.example para .env e preencha.` |
| Postgres desligado ou porta errada | Código 1, sem traceback. | `Não foi possível conectar ao Postgres em <host>:<porta>. Ele está em execução?` |
| Senha ou usuário incorretos | Código 1, sem traceback e sem exibir a senha. | `Falha de autenticação para o usuário "<usuário>".` |
| Banco não existe | Código 1. | `Banco "<nome>" não existe. Execute sql/setup_admin.sql.` |
| Extensão `vector` ausente no banco | `init-db` não aplica nada. Código 1. | `Extensão "vector" não instalada em "<banco>". Execute sql/setup_admin.sql como superusuário.` |
| Script de preparação sem `rag_password` | Para antes de qualquer mudança. | `Informe a senha: psql -v rag_password='...' -f sql/setup_admin.sql` |
| `init-db` repetido | Nenhum erro e nenhum dado alterado. | `Esquema já estava atualizado.` |
| Esquema incompleto (falta tabela ou índice) | `init-db` completa o que falta. `check` aponta o item ausente. | `[FALHA] Tabela chunks ausente. Execute init-db.` |
| `check` com variáveis opcionais ausentes (`ANTHROPIC_API_KEY`, `LLM_MODEL`, `EMBEDDING_MODEL`, `HF_TOKEN`) | Só aviso, não falha, pois são usadas por features futuras. | `[AVISO] LLM_MODEL não definida (necessária a partir da F07).` |
| Qualquer erro na aplicação do esquema | A transação inteira é desfeita. Nada fica pela metade. | Mensagem do erro, sem senha. |
| Comando `python -m src.cli` sem argumentos | Em terminal interativo abre o menu (F10); sem terminal, mostra a ajuda com os comandos disponíveis. | Lista de comandos. |

### 4.3 Saída para a pessoa

`init-db`
```
Conectado: localhost:5432/rag_training_db (usuário rag_user)
Extensão vector 0.8.7: OK
Tabelas criadas: sources, documents, chunks, app_meta
Índices criados: documents_sha256_uniq, chunks_embedding_hnsw, chunks_tsv_gin
Esquema aplicado com sucesso.
```

`check`
```
[OK]    DATABASE_URL definida: localhost:5432/rag_training_db (usuário rag_user)
[OK]    Conexão com o Postgres 18.6
[OK]    Extensão vector 0.8.7
[OK]    Tabelas: sources, documents, chunks, app_meta
[OK]    Índices: documents_sha256_uniq, chunks_embedding_hnsw, chunks_tsv_gin
[OK]    chunks.embedding com 1024 dimensões
[AVISO] HF_TOKEN não definida (opcional)
Resultado: ambiente OK (0 falhas, 1 aviso)
```

## 5. Interface

**Comandos da CLI** (`python -m src.cli`)

| Comando | Argumentos e opções | Descrição |
|---|---|---|
| `init-db` | nenhum | Confere conexão e extensão, aplica `sql/001_init.sql` em uma transação e resume o resultado. |
| `check` | nenhum | Verifica variáveis do `.env`, conexão, versão do Postgres, extensão, tabelas, índices e a dimensão do vetor. Código 0 sem falhas, 1 com falhas. Avisos não alteram o código. |

**Script de preparação (manual, uma vez)**
```
psql -d postgres -v rag_password='<SENHA>' -f sql/setup_admin.sql
```
Executado com o superusuário do Postgres local (hoje, o próprio usuário do macOS, `josejulio`).

**Módulos e funções**

| Arquivo | Responsabilidade | Funções / classes |
|---|---|---|
| `src/config.py` | Passa a expor `DATABASE_URL`. Sem valor padrão. | `DATABASE_URL` |
| `src/db.py` | Conexão e aplicação do esquema. | `connect()`, `init_db()`, `check_environment()`, `mask_url(url)` |
| `src/cli.py` | Entrada da CLI com `argparse`. | `main()` |
| `sql/setup_admin.sql` | Preparação feita pelo superusuário. | — |
| `sql/001_init.sql` | Esquema do banco. | — |

## 6. Dados

**`sql/setup_admin.sql`** (versionado, sem senha)
```sql
\if :{?rag_password}
\else
  \echo 'Informe a senha: psql -v rag_password=''...'' -f sql/setup_admin.sql'
  \quit
\endif
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE rag_user LOGIN PASSWORD %L', :'rag_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_user') \gexec

SELECT 'CREATE DATABASE rag_training_db OWNER rag_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag_training_db') \gexec

\connect rag_training_db
CREATE EXTENSION IF NOT EXISTS vector;
```
Se `rag_user` já existir, a senha **não** é alterada. Para trocá-la, use `ALTER ROLE` manualmente.

**`sql/001_init.sql`** — o mesmo esquema da ARQUITETURA §6, com `IF NOT EXISTS` em tabelas e índices:
```sql
CREATE TABLE IF NOT EXISTS sources (
  id              BIGSERIAL PRIMARY KEY,
  path            TEXT NOT NULL UNIQUE,
  recursive       BOOLEAN NOT NULL DEFAULT true,
  last_indexed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS documents (
  id          BIGSERIAL PRIMARY KEY,
  source_id   BIGINT REFERENCES sources(id) ON DELETE CASCADE,
  source_path TEXT NOT NULL UNIQUE,
  filename    TEXT NOT NULL,
  file_type   TEXT NOT NULL CHECK (file_type IN ('txt', 'pdf')),
  sha256      TEXT NOT NULL,
  pages       INT  NOT NULL,
  status      TEXT NOT NULL DEFAULT 'indexed' CHECK (status IN ('indexing', 'indexed', 'failed')),
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS documents_sha256_uniq ON documents (sha256);

CREATE TABLE IF NOT EXISTS chunks (
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
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin        ON chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS app_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```
`001_init.sql` **não** cria a extensão: isso exige superusuário e é feito pelo `setup_admin.sql`.

## 7. Configuração

| Parâmetro | Padrão | Onde se define |
|---|---|---|
| `DATABASE_URL` | Nenhum (obrigatória) | `.env`. Formato: `postgresql://rag_user:<SENHA>@localhost:5432/rag_training_db` |
| Placeholder no `.env.example` | `postgresql://rag_user:<SENHA>@localhost:5432/rag_training_db` | `.env.example` (sem a senha real) |

## 8. Dependências externas
- **Python:** `psycopg[binary]` (psycopg 3), adicionado ao `requirements.txt`.
- **Serviço:** PostgreSQL 18.6 (Homebrew) em execução, com pgvector 0.8.7 já instalado e disponível.
- **Cliente:** `psql`, usado só no script de preparação e nas conferências do roteiro.
- Sem arquivos de exemplo.

## 9. Critérios de aceite — roteiro de teste manual

**Pré-condições:** Postgres em execução; pgvector 0.8.7 instalado; estado inicial **sem** `rag_user` nem `rag_training_db`; ambiente virtual ativo com `pip install -r requirements.txt`; comandos executados da raiz do projeto.

| # | Passo | Comando / ação | Resultado esperado |
|---|---|---|---|
| 1 | Ajuda da CLI | `python -m src.cli` | Lista `init-db` e `check`. Código 0. |
| 2 | `check` sem `DATABASE_URL` | Com a variável ausente do `.env`: `python -m src.cli check; echo $?` | `[FALHA] DATABASE_URL não definida…`. Código 1. Nenhum traceback. |
| 3 | Script sem senha | `psql -d postgres -f sql/setup_admin.sql` | Mensagem pedindo `rag_password`. Nada criado (confira com a consulta A). |
| 4 | Preparação | `psql -d postgres -v rag_password='<SENHA>' -f sql/setup_admin.sql` | Sem erros. Consulta A mostra `rag_user` e `rag_training_db`, e consulta B mostra `vector 0.8.7`. |
| 5 | Preparação repetida | Repetir o passo 4 | Sem erros e nada duplicado. A senha de `rag_user` continua a mesma (o passo 7 conecta com ela). |
| 6 | Definir acesso | Adicionar `DATABASE_URL=postgresql://rag_user:<SENHA>@localhost:5432/rag_training_db` ao `.env` | — |
| 7 | `check` antes do esquema | `python -m src.cli check; echo $?` | `[OK]` na conexão e na extensão. `[FALHA]` para tabelas e índices ausentes. Código 1. |
| 8 | Aplicar esquema | `python -m src.cli init-db` | Saída conforme 4.3. Consulta C lista as 4 tabelas. Consulta D lista os 3 índices. |
| 9 | Esquema repetido | `python -m src.cli init-db` | `Esquema já estava atualizado.` Sem erros. |
| 10 | `check` completo | `python -m src.cli check; echo $?` | Todos `[OK]`. Código 0. Variáveis opcionais ausentes aparecem como `[AVISO]`. |
| 11 | Dados preservados | Inserir os dados de teste (consulta E), rodar `init-db`, e consultar `chunks` | A linha continua lá após o `init-db`. |
| 12 | Coluna textual | Consulta F | `tsv` preenchido com termos em português (ex.: `ferias`). |
| 13 | Duplicado barrado | Inserir outro `documents` com o mesmo `sha256` (consulta G) | Erro de chave duplicada. |
| 14 | Remoção em cascata | `DELETE FROM documents WHERE sha256 = 'teste-f01'` e contar `chunks` | O chunk de teste também some (0 linhas). |
| 15 | Status inválido | Inserir `documents` com `status = 'x'` (consulta H) | Erro de restrição `CHECK`. |
| 16 | Senha errada | Trocar a senha no `DATABASE_URL`: `python -m src.cli check` | `Falha de autenticação para o usuário "rag_user".` Sem traceback e **sem a senha** na saída. |
| 17 | Banco inexistente | Trocar o nome do banco na URL: `python -m src.cli check` | `Banco "<nome>" não existe…`. Código 1. |
| 18 | Postgres desligado | `brew services stop postgresql@18`, rodar `check`, depois `brew services start postgresql@18` | Mensagem de conexão (4.2), sem traceback. Voltou ao normal depois de religar. |
| 19 | Extensão ausente | Criar banco vazio de teste (consulta I), apontar `DATABASE_URL` para ele e rodar `init-db` | Mensagem de extensão ausente. Nenhuma tabela criada nesse banco. Depois, remover o banco (consulta I) e restaurar o `.env`. |
| 20 | Atomicidade | Alterar temporariamente uma linha de `001_init.sql` para um SQL inválido no meio, em banco de teste vazio com `vector`, e rodar `init-db` | Erro exibido. Nenhuma tabela criada (a transação foi desfeita). Restaurar o arquivo. |
| 21 | Senha fora do versionado | `git grep -n '<SENHA real>' -- . ':!.env'` | Nenhuma ocorrência. |

**Consultas úteis**
```sql
-- A) papel e banco
SELECT rolname FROM pg_roles WHERE rolname = 'rag_user';
SELECT datname FROM pg_database WHERE datname = 'rag_training_db';
-- B) extensão (conectado em rag_training_db)
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
-- C) tabelas
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1;
-- D) índices
SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1;
-- E) dados de teste
INSERT INTO documents (source_path, filename, file_type, sha256, pages)
  VALUES ('/tmp/teste-f01.txt', 'teste-f01.txt', 'txt', 'teste-f01', 1);
INSERT INTO chunks (document_id, chunk_index, content, embedding)
  SELECT id, 0, 'Férias e trabalho remoto', array_fill(0.1::real, ARRAY[1024])::vector
  FROM documents WHERE sha256 = 'teste-f01';
-- F) coluna textual
SELECT tsv FROM chunks;
-- G) duplicado
INSERT INTO documents (source_path, filename, file_type, sha256, pages)
  VALUES ('/tmp/outro.txt', 'outro.txt', 'txt', 'teste-f01', 1);
-- H) status inválido
INSERT INTO documents (source_path, filename, file_type, sha256, pages, status)
  VALUES ('/tmp/x.txt', 'x.txt', 'txt', 'x', 1, 'x');
-- I) banco de teste sem extensão (conectado como superusuário em "postgres")
CREATE DATABASE rag_teste_sem_vector OWNER rag_user;
DROP DATABASE rag_teste_sem_vector;
```
Conexão para os testes de banco: `psql "postgresql://rag_user:<SENHA>@localhost:5432/rag_training_db"` (ou `psql -d rag_training_db` como superusuário, para as consultas A e B).

## 10. Impacto em outras features

| Feature | Roteiros a repetir (#) | Motivo |
|---|---|---|
| Código atual (`scripts/`) | `python -c "from src.config import LLM_MODEL, EMBEDDING_MODEL; print(LLM_MODEL, EMBEDDING_MODEL)"` | `config.py` é alterado e o restante do código depende dele. Opcional: `python -m scripts.check_setup`. |
| Nenhuma outra feature implementada | — | F01 é a base. Mudanças futuras no esquema exigirão repetir os passos 8 a 15. |

## 11. Riscos e decisões

**Decisões tomadas** (com o motivo)
- **Preparação por script SQL manual**, e não pela CLI: a aplicação nunca precisa de credencial de superusuário (T1).
- **Esquema completo já na F01**, incluindo `tsv` em português: evita remendos depois. Se a F06 mudar o idioma, vira uma migração (as tabelas ainda estarão vazias).
- **`check` só de configuração e banco**: evita carregar o modelo de ~2 GB a cada verificação. Embeddings entram na F04 e o Claude na F07.
- **`init-db` não grava o modelo de embeddings**: isso exige carregar o modelo e pertence à F04. **A ARQUITETURA §8 (`init-db`) precisa ser ajustada** (ver seção 12).
- **Sem pool de conexões e sem o pacote `pgvector` do Python nesta feature**: só entram com quem os usa (F05/F06).
- **Variáveis opcionais ausentes são só aviso** no `check`, pois dependem de features futuras.
- **A senha de `rag_user` não é alterada** pela repetição do script de preparação: evita trocar a senha sem querer.
- **Banco principal sem dados de teste permanentes:** os dados do roteiro são removidos no passo 14.
- **Risco aceito:** conferir o esquema só pelo `check` (nomes de tabelas e índices e a dimensão). Diferenças finas, como tipos de colunas, não são verificadas automaticamente.

**Pontos em aberto** (não bloqueiam a F01)
- **Mecanismo para migrações futuras** (`002_*.sql`): como `init-db` saberá quais já foram aplicadas. Será decidido quando a primeira migração for necessária (provavelmente a F06).
- **Idioma da coluna `tsv`** (português e inglês): decisão da F06.

## 12. Documentação a atualizar
- `.env.example`: acrescentar `DATABASE_URL` com o placeholder `<SENHA>`.
- `requirements.txt`: acrescentar `psycopg[binary]`.
- `ARQUITETURA.md` (**já aplicado**): §8, `init-db` deixa de gravar o modelo de embeddings (passa para a F04) e `check` na F01 cobre só configuração e banco; §10, incluir `sql/setup_admin.sql`; §9, `pool` e `pgvector` entram depois.
- `ROADMAP.md`: status da F01.
- `CLAUDE.md` (agora em `.claude/CLAUDE.md`): só o estado do projeto foi atualizado. Os comandos não foram incluídos, pois a seção de comandos foi removida do arquivo.
- `README.md`: fica para a F12.

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
| 2026-10-02 | Jose Julio | Aprovado | Roteiro da seção 9 executado (passos 1 a 21), sem falhas, conforme relato da pessoa. Regressão da seção 10 (`src.config`) conferida na implementação. |
