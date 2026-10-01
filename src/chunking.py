import re

import numpy as np

def fixed_size_chunks(text: str, chunk_size: int = 400, overlap: int = 80) -> list[str]:
    """Corta a cada `chunk_size` caracteres, com sobreposição de `overlap`."""
    if overlap >= chunk_size:
        raise ValueError("overlap deve ser menor que chunk_size")

    step = chunk_size - overlap
    chunks = []
    start = 0
    while start < len(text):
        piece = text[start : start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        if start + chunk_size >= len(text):
            break
        start += step
    return chunks


def split_sentences(text: str) -> list[str]:
    """Divisão simples de sentenças (ponto, exclamação, interrogação)."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def sentence_chunks(
    text: str, max_chars: int = 400, overlap_sentences: int = 1
) -> list[str]:
    """Agrupa sentenças inteiras até `max_chars`, repetindo as últimas
    `overlap_sentences` sentenças no início do chunk seguinte."""
    sentences = split_sentences(text)
    chunks = []
    current: list[str] = []

    for sentence in sentences:
        if current and len(" ".join(current + [sentence])) > max_chars:
            chunks.append(" ".join(current))
            current = current[-overlap_sentences:] if overlap_sentences else []
        current.append(sentence)

    if current:
        chunks.append(" ".join(current))
    return chunks


def recursive_chunks(
    text: str,
    chunk_size: int = 400,
    overlap: int = 60,
    separators: list[str] | None = None,
) -> list[str]:
    """Tenta cortar pelo separador mais 'natural' primeiro (parágrafo), e só
    desce para separadores menores (linha, frase, palavra) quando necessário."""
    separators = separators or ["\n\n", "\n", ". ", " "]

    def split(t: str, seps: list[str]) -> list[str]:
        if len(t) <= chunk_size:
            return [t]
        if not seps:
            return [t[i : i + chunk_size] for i in range(0, len(t), chunk_size)]

        sep, rest = seps[0], seps[1:]
        pieces = []
        for part in t.split(sep):
            if len(part) > chunk_size:
                pieces.extend(split(part, rest))
            else:
                pieces.append(part)

        # Junta pedaços pequenos vizinhos até o limite de tamanho
        merged, current = [], ""
        for piece in pieces:
            candidate = f"{current}{sep}{piece}" if current else piece
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    merged.append(current)
                current = piece
        if current:
            merged.append(current)
        return merged

    chunks = [c.strip() for c in split(text, separators) if c.strip()]

    if overlap <= 0:
        return chunks

    # Aplica overlap: cauda do chunk anterior (sem cortar palavra) no início do próximo
    result = [chunks[0]]
    for prev, cur in zip(chunks, chunks[1:]):
        tail = prev[-overlap:]
        if " " in tail:
            tail = tail[tail.index(" ") + 1 :]
        result.append(f"{tail} {cur}")
    return result


def semantic_chunks(text: str, model, percentile: float = 25) -> list[str]:
    """Corta onde a similaridade entre sentenças consecutivas cai.
    `percentile`: as quedas de similaridade abaixo desse percentil viram cortes."""
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return sentences

    embeddings = model.encode(sentences, normalize_embeddings=True)
    # Vetores normalizados: produto escalar = similaridade de cosseno
    similarities = (embeddings[:-1] * embeddings[1:]).sum(axis=1)
    cutoff = np.percentile(similarities, percentile)

    chunks = []
    current = [sentences[0]]
    for i, sim in enumerate(similarities):
        if sim < cutoff:
            chunks.append(" ".join(current))
            current = []
        current.append(sentences[i + 1])
    chunks.append(" ".join(current))
    return chunks
