import itertools
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

import numpy as np

from src.loaders import Page

MAX_CHARS = 900
OVERLAP_CHARS = 110
STRATEGIES = ("structured", "fixed", "sentence", "recursive", "semantic")

ABBREVIATIONS = {
    "sr", "sra", "dr", "dra", "prof", "profa", "eng", "av", "ex", "etc",
    "vs", "mr", "mrs", "ms", "st",
}


@dataclass(frozen=True)
class Chunk:
    chunk_index: int  # sequencial no documento, a partir de 0
    page: int  # 1-based, igual à página do PDF
    section: str | None  # caminho de títulos, ex.: "Manual > Férias"
    content: str  # texto limpo, sem o prefixo de seção

    @property
    def embedding_text(self) -> str:
        """Texto para embedding (e, se decidido, busca textual): seção + conteúdo."""
        return f"{self.section}\n\n{self.content}" if self.section else self.content


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


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LIST_ITEM = re.compile(r"^\d+[.)]$")
_SENTENCE_START_MARKS = "\"'“‘«(-*•["


def _is_sentence_boundary(last_word: str, next_char: str) -> bool:
    """Decide se o ponto/!/? depois de `last_word` encerra mesmo a sentença."""
    if last_word.endswith("."):
        if last_word.rstrip(".").lstrip("(\"'“‘«").lower() in ABBREVIATIONS:
            return False
    if _LIST_ITEM.match(last_word):
        return False
    return not next_char or next_char.isupper() or next_char.isdigit() or next_char in _SENTENCE_START_MARKS


def split_sentences(text: str) -> list[str]:
    """Divide em sentenças (ponto, exclamação, interrogação), sem cortar
    abreviações ("Sr.", "etc."), itens numerados ("1.") nem números ("3,5")."""
    sentences = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        before = text[start : match.start()]
        words = text[max(start, match.start() - 30) : match.start()].split()
        last_word = words[-1] if words else ""
        if _is_sentence_boundary(last_word, text[match.end() : match.end() + 1]):
            sentences.append(before)
            start = match.end()
    sentences.append(text[start:])
    return [s.strip() for s in sentences if s.strip()]


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
        parts = t.split(sep)
        joiner = sep
        if sep == ". ":  # o ponto fica no fim da frase, não se perde ao cortar
            parts = [p + "." for p in parts[:-1]] + parts[-1:]
            joiner = " "

        pieces = []
        for part in parts:
            if len(part) > chunk_size:
                pieces.extend(split(part, rest))
            else:
                pieces.append(part)

        # Junta pedaços pequenos vizinhos até o limite de tamanho
        merged, current = [], ""
        for piece in pieces:
            candidate = f"{current}{joiner}{piece}" if current else piece
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
    if not chunks:
        return []

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


def semantic_chunks(
    text: str,
    model,
    percentile: float = 25,
    min_chars: int = 200,
    max_chars: int = 1000,
) -> list[str]:
    """Corta onde a similaridade entre sentenças consecutivas cai.
    `percentile`: as quedas de similaridade abaixo desse percentil viram cortes.
    Trechos menores que `min_chars` são unidos ao vizinho; maiores que
    `max_chars` são redivididos."""
    sentences = split_sentences(text)
    if len(sentences) < 2:
        chunks = sentences
    else:
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

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < min_chars and len(merged[-1]) + 1 + len(chunk) <= max_chars:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)
    if len(merged) > 1 and len(merged[-1]) < min_chars and len(merged[-2]) + 1 + len(merged[-1]) <= max_chars:
        merged[-2:] = [f"{merged[-2]} {merged[-1]}"]

    result: list[str] = []
    for chunk in merged:
        result.extend(recursive_chunks(chunk, max_chars, 0) if len(chunk) > max_chars else [chunk])
    return result


# --- Estratégia estruturada (padrão): títulos Markdown -> parágrafo -> sentença -> tamanho ---

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]+\|?$")
_MAX_SECTION_LEVEL = 3


def _check_params(max_chars: int, overlap_chars: int) -> None:
    if max_chars <= 0:
        raise ValueError("max_chars deve ser maior que zero")
    if overlap_chars < 0:
        raise ValueError("overlap_chars não pode ser negativo")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars deve ser menor que max_chars")


def _blocks(text: str) -> Iterator[tuple[str, object]]:
    """Quebra o Markdown de uma página em blocos: ("heading", (nível, título)),
    ("table", [linhas]) e ("para", texto)."""
    para: list[str] = []
    table: list[str] = []

    def close() -> Iterator[tuple[str, object]]:
        if para:
            yield "para", "\n".join(para).strip()
            para.clear()
        if table:
            yield "table", list(table)
            table.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _HEADING.match(line)
        if heading:
            title = heading.group(2).strip("*_# ").strip()
            if title:
                yield from close()
                yield "heading", (len(heading.group(1)), title)
            continue
        if not line.strip():
            yield from close()
        elif line.lstrip().startswith("|"):
            if para:
                yield from close()
            table.append(line.strip())
        else:
            if table:
                yield from close()
            para.append(line)
    yield from close()


def _split_long(text: str, limit: int) -> list[str]:
    """Divide um texto maior que `limit` por sentença e, por último, por palavra."""
    pieces: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        current = ""
        for word in sentence.split():
            while len(word) > limit:  # palavra gigante (ex.: URL): corte por tamanho
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(word[:limit])
                word = word[limit:]
            candidate = f"{current} {word}" if current else word
            if len(candidate) <= limit:
                current = candidate
            else:
                pieces.append(current)
                current = word
        if current:
            pieces.append(current)
    return pieces


def _overlap_tail(text: str, size: int) -> str:
    """Fim de `text` com até `size` caracteres, sem começar no meio de uma palavra."""
    if size <= 0:
        return ""
    if len(text) <= size:
        return text
    tail = text[-size:]
    if not text[-size - 1].isspace():
        space = re.search(r"\s", tail)
        tail = tail[space.end() :] if space else ""
    return tail.strip()


def _pack_paragraphs(paragraphs: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    """Agrupa parágrafos de uma mesma seção/página em trechos de até `max_chars`,
    já com o overlap (que conta dentro do limite)."""
    rest_limit = max(max_chars - overlap_chars - 1, 1)  # trechos que recebem overlap

    atoms: list[tuple[str, str]] = []  # (texto, separador antes dele)
    for paragraph in paragraphs:
        if len(paragraph) <= rest_limit:
            atoms.append((paragraph, "\n\n"))
        else:
            first, *others = _split_long(paragraph, rest_limit)
            atoms.append((first, "\n\n"))
            atoms.extend((piece, " ") for piece in others)

    contents: list[str] = []
    current = ""
    for text, sep in atoms:
        limit = max_chars if not contents else rest_limit
        candidate = f"{current}{sep}{text}" if current else text
        if len(candidate) <= limit:
            current = candidate
        else:
            contents.append(current)
            current = text
    if current:
        contents.append(current)

    result = contents[:1]
    for prev, content in zip(contents, contents[1:]):
        tail = _overlap_tail(prev, overlap_chars)
        result.append(f"{tail} {content}" if tail else content)
    return result


def _table_chunks(lines: list[str], max_chars: int) -> list[str]:
    """Divide uma tabela entre linhas, repetindo o cabeçalho em cada parte."""
    header = lines[:2] if len(lines) >= 2 and _TABLE_SEPARATOR.match(lines[1]) else []
    rows = lines[len(header) :]
    if not rows:
        return ["\n".join(header)]

    parts: list[str] = []
    current: list[str] = []
    for row in rows:
        if current and len("\n".join(header + current + [row])) > max_chars:
            parts.append("\n".join(header + current))
            current = []
        current.append(row)
    parts.append("\n".join(header + current))
    return parts


def structured_chunks(
    pages: Iterable[Page],
    max_chars: int = MAX_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> Iterator[Chunk]:
    """Divide por títulos Markdown, depois parágrafo, sentença e tamanho.

    Cada trecho pertence a uma só página e a uma só seção; a seção (caminho de
    títulos) continua valendo nas páginas seguintes até aparecer outro título.
    """
    _check_params(max_chars, overlap_chars)
    counter = itertools.count()
    titles: list[str] = []

    def make(page: int, contents: list[str]) -> Iterator[Chunk]:
        section = " > ".join(titles) or None
        for content in contents:
            yield Chunk(next(counter), page, section, content)

    for page in pages:
        paragraphs: list[str] = []
        for kind, value in _blocks(page.text):
            if kind == "para":
                paragraphs.append(value)
                continue
            # título ou tabela encerram os parágrafos pendentes
            yield from make(page.number, _pack_paragraphs(paragraphs, max_chars, overlap_chars))
            paragraphs = []
            if kind == "heading":
                level, title = value
                titles = titles[: level - 1] + [title]
            else:
                yield from make(page.number, _table_chunks(value, max_chars))
        yield from make(page.number, _pack_paragraphs(paragraphs, max_chars, overlap_chars))


def chunk_pages(
    pages: Iterable[Page],
    strategy: str = "structured",
    model=None,
    max_chars: int = MAX_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> Iterator[Chunk]:
    """Ponto único de entrada: divide as páginas com a estratégia escolhida.

    As estratégias antigas são aplicadas página a página e saem sem seção.
    `overlap_chars` vira o overlap em caracteres (fixed, recursive) ou, em
    `sentence`, uma sentença de overlap (0 = sem overlap).
    """
    if strategy not in STRATEGIES:
        raise ValueError(f'Estratégia desconhecida: "{strategy}". Use: {", ".join(STRATEGIES)}.')
    if strategy == "semantic" and model is None:
        raise ValueError("A estratégia semantic exige o parâmetro model.")
    _check_params(max_chars, overlap_chars)

    if strategy == "structured":
        return structured_chunks(pages, max_chars, overlap_chars)

    splitters: dict[str, Callable[[str], list[str]]] = {
        "fixed": lambda t: fixed_size_chunks(t, max_chars, overlap_chars),
        "sentence": lambda t: sentence_chunks(t, max_chars, 1 if overlap_chars else 0),
        "recursive": lambda t: recursive_chunks(t, max_chars, overlap_chars),
        "semantic": lambda t: semantic_chunks(t, model, max_chars=max_chars),
    }
    split = splitters[strategy]

    def run() -> Iterator[Chunk]:
        counter = itertools.count()
        for page in pages:
            for content in split(page.text):
                yield Chunk(next(counter), page.number, None, content)

    return run()
