-- Esquema da aplicação (ver .spec/ARQUITETURA.md §6). Idempotente.
-- A extensão "vector" NÃO é criada aqui: exige superusuário (ver sql/setup_admin.sql).

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
