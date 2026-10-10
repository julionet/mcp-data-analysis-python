-- Busca textual em português e inglês (F06). Idempotente.
-- `tsv` (português) e `tsv_en` (inglês) cobrem seção (peso C) e conteúdo (peso A).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'public' AND table_name = 'chunks' AND column_name = 'tsv_en') THEN
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
