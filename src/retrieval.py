from dataclasses import dataclass

import numpy as np
import psycopg

from src.db import DbError
from src.repository import folder_prefix

METHODS = ("rrf", "semantic", "lexical")
TOP_K = 5
FETCH_K = 20
RRF_K = 60

_ALLOWED = (
    "d.status = 'indexed' "
    "AND (%(prefix)s::text IS NULL OR starts_with(d.source_path, %(prefix)s::text))"
)

# Termos da pergunta combinados por OU, sem palavras vazias de nenhum dos dois idiomas
# (decisão da F06: a coluna em inglês indexa "de", "o", "e" do português como palavras comuns).
_QUERY = """
words AS (
  SELECT w FROM unnest(tsvector_to_array(to_tsvector('simple', %(text)s))) w
  WHERE ts_lexize('portuguese_stem', w) IS DISTINCT FROM '{}'
    AND ts_lexize('english_stem', w)    IS DISTINCT FROM '{}'
),
q AS (
  SELECT to_tsquery('portuguese', string_agg(quote_literal(w), ' | ')) AS pt,
         to_tsquery('english',    string_agg(quote_literal(w), ' | ')) AS en
  FROM words
)"""

_SEMANTIC = f"""
sem AS (
  SELECT c.id,
         1 - (c.embedding <=> %(vec)s::vector) AS score,
         ROW_NUMBER() OVER (ORDER BY c.embedding <=> %(vec)s::vector, c.id) AS rank
  FROM chunks c JOIN documents d ON d.id = c.document_id
  WHERE {_ALLOWED}
  ORDER BY c.embedding <=> %(vec)s::vector, c.id
  LIMIT %(fetch_k)s
)"""

_LEXICAL = f"""
lex AS (
  SELECT c.id,
         GREATEST(ts_rank_cd(c.tsv, q.pt), ts_rank_cd(c.tsv_en, q.en)) AS score,
         ROW_NUMBER() OVER (
           ORDER BY GREATEST(ts_rank_cd(c.tsv, q.pt), ts_rank_cd(c.tsv_en, q.en)) DESC, c.id
         ) AS rank
  FROM chunks c JOIN documents d ON d.id = c.document_id, q
  WHERE {_ALLOWED} AND (c.tsv @@ q.pt OR c.tsv_en @@ q.en)
  ORDER BY GREATEST(ts_rank_cd(c.tsv, q.pt), ts_rank_cd(c.tsv_en, q.en)) DESC, c.id
  LIMIT %(fetch_k)s
)"""

_COLUMNS = (
    "c.id, d.id, d.source_path, d.filename, c.page, c.section, c.content"
)

_SQL = {
    "semantic": f"""
WITH {_SEMANTIC.strip()}
SELECT {_COLUMNS}, sem.score, sem.rank, sem.score, NULL::bigint, NULL::real
FROM sem JOIN chunks c ON c.id = sem.id JOIN documents d ON d.id = c.document_id
ORDER BY sem.rank LIMIT %(top_k)s""",
    "lexical": f"""
WITH {_QUERY.strip()}, {_LEXICAL.strip()}
SELECT {_COLUMNS}, lex.score, NULL::bigint, NULL::real, lex.rank, lex.score
FROM lex JOIN chunks c ON c.id = lex.id JOIN documents d ON d.id = c.document_id
ORDER BY lex.rank LIMIT %(top_k)s""",
    "rrf": f"""
WITH {_SEMANTIC.strip()}, {_QUERY.strip()}, {_LEXICAL.strip()},
fused AS (
  SELECT COALESCE(sem.id, lex.id) AS id,
         COALESCE(1.0 / (%(rrf_k)s + sem.rank), 0) + COALESCE(1.0 / (%(rrf_k)s + lex.rank), 0) AS score,
         sem.rank AS sem_rank, sem.score AS sem_score, lex.rank AS lex_rank, lex.score AS lex_score
  FROM sem FULL OUTER JOIN lex ON lex.id = sem.id
)
SELECT {_COLUMNS}, fused.score, fused.sem_rank, fused.sem_score, fused.lex_rank, fused.lex_score
FROM fused JOIN chunks c ON c.id = fused.id JOIN documents d ON d.id = c.document_id
ORDER BY fused.score DESC, c.id LIMIT %(top_k)s""",
}


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    document_id: int
    source_path: str
    filename: str
    page: int | None
    section: str | None
    content: str
    score: float
    semantic_rank: int | None = None
    semantic_score: float | None = None  # similaridade de cosseno
    lexical_rank: int | None = None
    lexical_score: float | None = None  # ts_rank_cd


def search(
    conn: psycopg.Connection,
    text: str,
    vector: np.ndarray | None,
    method: str = "rrf",
    top_k: int = TOP_K,
    fetch_k: int = FETCH_K,
    folder: str | None = None,
) -> list[SearchHit]:
    """Trechos mais relevantes de documentos `indexed`, em SQL (F06, seção 6).

    `vector` é obrigatório em `semantic` e `rrf`; em `lexical` é ignorado.
    """
    if method not in METHODS:
        raise ValueError(f'Método desconhecido: "{method}". Use: {", ".join(METHODS)}.')
    if top_k <= 0 or fetch_k <= 0:
        raise ValueError("top_k e fetch_k devem ser maiores que zero.")
    if method != "lexical" and vector is None:
        raise ValueError(f'O método "{method}" exige o vetor da pergunta.')

    params = {
        "text": text,
        "vec": vector,
        "prefix": folder_prefix(folder),
        "top_k": top_k,
        "fetch_k": max(fetch_k, top_k),
        "rrf_k": RRF_K,
    }
    try:
        with conn.transaction():
            # com filtro, o índice HNSW não pode esvaziar o resultado (pgvector 0.8)
            conn.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
            rows = conn.execute(_SQL[method], params).fetchall()
    except psycopg.errors.UndefinedColumn:
        raise DbError("Busca textual desatualizada. Execute init-db.") from None
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabelas ausentes. Execute init-db.") from None
    return [SearchHit(*row[:8], semantic_rank=row[8], semantic_score=row[9], lexical_rank=row[10], lexical_score=row[11])
            for row in rows]
