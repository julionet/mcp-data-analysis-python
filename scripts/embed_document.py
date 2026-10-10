import argparse
import sys
import time

import numpy as np

from src import config, db
from src.chunking import MAX_CHARS, OVERLAP_CHARS, Chunk, chunk_pages
from src.embeddings import (
    BATCH_SIZE,
    MAX_SEQ_LENGTH,
    EmbedStats,
    Embedder,
    EmbeddingError,
    embed_chunks,
)
from src.loaders import LoaderError, inspect_document, iter_pages


def _show_count(value: str) -> int | None:
    """None = mostrar todos."""
    if value == "all":
        return None
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('use um número ou "all"') from None
    if count < 0:
        raise argparse.ArgumentTypeError("não pode ser negativo")
    return count


def _fmt(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _vector_preview(vector: np.ndarray) -> str:
    head = " ".join(_fmt(float(x)) for x in vector[:3])
    return f"[{head} …]"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.embed_document",
        description="Vetoriza os trechos de um TXT, MD ou PDF e mostra o resultado (apoio ao teste da F04).",
    )
    parser.add_argument("arquivo")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS)
    parser.add_argument("--overlap", type=int, default=OVERLAP_CHARS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--max-seq-length", type=int, default=MAX_SEQ_LENGTH)
    parser.add_argument("--show", type=_show_count, default=5, metavar="N|all")
    parser.add_argument("--query", help="lista os 3 trechos mais próximos desta consulta (em memória)")
    parser.add_argument("--no-db", action="store_true", help="não consulta nem grava app_meta")
    args = parser.parse_args(argv)

    conn = None
    try:
        model_name = config.EMBEDDING_MODEL
        if not model_name:
            raise EmbeddingError("EMBEDDING_MODEL não definida. Copie .env.example para .env e preencha.")

        info = inspect_document(args.arquivo)

        registered = False
        if not args.no_db:
            conn = db.connect()
            registered = db.ensure_embedding_model(conn, model_name)  # falha antes de carregar o modelo

        embedder = Embedder(model_name, args.batch_size, args.max_seq_length)
        embedder.check_dimension(db.EMBEDDING_DIM)

        chunks = chunk_pages(
            iter_pages(args.arquivo),
            "structured",
            max_chars=args.max_chars,
            overlap_chars=args.overlap,
        )
        stats = EmbedStats()
        norm_min = norm_max = 0.0
        first = True
        shown: list[tuple[Chunk, np.ndarray]] = []
        kept: list[tuple[Chunk, np.ndarray]] = []  # só com --query
        started = time.perf_counter()
        for chunk, vector in embed_chunks(embedder, chunks, stats=stats):
            norm = float(np.linalg.norm(vector))
            norm_min = norm if first else min(norm_min, norm)
            norm_max = max(norm_max, norm)
            first = False
            if args.show is None or len(shown) < args.show:
                shown.append((chunk, vector))
            if args.query:
                kept.append((chunk, vector))
        elapsed = time.perf_counter() - started

        if args.no_db:
            register_note = "ignorado (--no-db)"
        elif stats.count == 0:
            register_note = "não gravado (nenhum trecho vetorizado)"
        elif registered:
            register_note = "já registrado, confere"
        else:
            db.register_embedding_model(conn, model_name, embedder.dimension)
            register_note = "gravado em app_meta (primeira vetorização)"

        query_vector = embedder.embed_one(args.query) if args.query else None
    except (LoaderError, EmbeddingError, db.DbError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    pages = f"{info.page_count} página" + ("s" if info.page_count != 1 else "")
    print(f"Arquivo:    {info.filename} ({info.file_type}, {pages})")
    print(
        f"Modelo:     {embedder.model_name} | dispositivo: {embedder.device} | "
        f"dimensão: {embedder.dimension} | max_seq_length: {embedder.max_seq_length}"
    )
    print(f"Registro:   {register_note}")
    if stats.count:
        print(
            f"Trechos:    {stats.count} | tokens mín {stats.token_min} · "
            f"média {stats.token_total // stats.count} · máx {stats.token_max} | "
            f"acima do limite: {len(stats.over_limit)}"
        )
        rate = stats.count / elapsed if elapsed else 0.0
        print(
            f"Vetores:    {stats.count} em {_fmt(elapsed, 1)} s ({_fmt(rate, 1)} trechos/s) | "
            f"norma mín {_fmt(norm_min)} · máx {_fmt(norm_max)}"
        )
    else:
        print("Trechos:    0")

    for chunk, vector in shown:
        section = chunk.section or "—"
        print(
            f"--- Trecho {chunk.chunk_index} | página {chunk.page} | seção: {section} "
            f"| vetor {_vector_preview(vector)} ---"
        )

    if query_vector is not None and kept:
        matrix = np.stack([v for _, v in kept])
        scores = matrix @ query_vector
        print("Mais parecidos com a consulta (cosseno):")
        for i in np.argsort(-scores)[:3]:
            chunk = kept[i][0]
            print(f"  {_fmt(float(scores[i]), 2)}  trecho {chunk.chunk_index} | seção: {chunk.section or '—'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
