from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    import pymupdf

ACCEPTED_TYPES = {".txt": "txt", ".md": "md", ".pdf": "pdf"}
TEXT_TYPES = {"txt", "md"}  # lidos como texto simples, em uma página
HASH_BLOCK_SIZE = 1024 * 1024


class LoaderError(Exception):
    """Erro esperado, com mensagem já pronta para a pessoa."""


@dataclass(frozen=True)
class Page:
    number: int  # 1-based, igual à página do PDF
    text: str


@dataclass(frozen=True)
class DocumentInfo:
    filename: str
    file_type: str
    sha256: str
    page_count: int


@dataclass(frozen=True)
class Document:
    filename: str
    file_type: str
    sha256: str
    pages: list[Page]


def _file_type(path: Path) -> str:
    if not path.exists() or path.is_dir():
        raise LoaderError(f"Arquivo não encontrado: {path}")
    file_type = ACCEPTED_TYPES.get(path.suffix.lower())
    if file_type is None:
        found = f'"{path.suffix}"' if path.suffix else "sem extensão"
        raise LoaderError(f"Formato não aceito: {found} ({path.name}). Use .txt, .md ou .pdf.")
    return file_type


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while block := f.read(HASH_BLOCK_SIZE):
                digest.update(block)
    except PermissionError:
        raise LoaderError(f"Sem permissão para ler: {path.name}") from None
    return digest.hexdigest()


def _read_txt(path: Path) -> str:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return text.strip()


def _open_pdf(path: Path) -> pymupdf.Document:
    """Abre o PDF e confere que é legível e sem senha; quem chama fecha."""
    import pymupdf  # import tardio: ver F04, seção 11

    try:
        doc = pymupdf.open(path, filetype="pdf")
    except Exception:
        raise LoaderError(
            f"Não foi possível ler o PDF: {path.name} (arquivo corrompido ou inválido)."
        ) from None
    if not doc.is_pdf:  # o PyMuPDF abre outros formatos pelo conteúdo, ignorando a extensão
        doc.close()
        raise LoaderError(
            f"Não foi possível ler o PDF: {path.name} (arquivo corrompido ou inválido)."
        )
    if doc.needs_pass:
        doc.close()
        raise LoaderError(f"PDF protegido por senha: {path.name}.")
    return doc


def _pdf_has_text(doc: pymupdf.Document, path: Path) -> bool:
    try:
        return any(page.get_text().strip() for page in doc)
    except Exception:
        raise LoaderError(
            f"Não foi possível ler o PDF: {path.name} (arquivo corrompido ou inválido)."
        ) from None


def inspect_document(path: str | Path) -> DocumentInfo:
    """Valida o arquivo e devolve seus dados, sem converter nenhuma página.

    Todos os erros de leitura (formato, vazio, sem texto, corrompido) saem aqui.
    """
    path = Path(path)
    file_type = _file_type(path)
    sha256 = _sha256(path)

    if file_type in TEXT_TYPES:
        if not _read_txt(path):
            raise LoaderError(f"Arquivo sem texto: {path.name}")
        return DocumentInfo(path.name, file_type, sha256, 1)

    doc = _open_pdf(path)
    try:
        if not _pdf_has_text(doc, path):
            raise LoaderError(
                f"PDF sem texto selecionável (provavelmente escaneado): {path.name}. "
                "Não há suporte a OCR."
            )
        return DocumentInfo(path.name, "pdf", sha256, len(doc))
    finally:
        doc.close()


def _pages(path: Path, file_type: str) -> Iterator[Page]:
    if file_type in TEXT_TYPES:
        yield Page(1, _read_txt(path))
        return

    doc = _open_pdf(path)
    try:
        for index in range(len(doc)):
            try:
                import pymupdf4llm

                markdown = pymupdf4llm.to_markdown(doc, pages=[index])
            except Exception:
                raise LoaderError(
                    f"Não foi possível ler a página {index + 1} do PDF: {path.name}."
                ) from None
            yield Page(index + 1, markdown.strip())
    finally:
        doc.close()


def iter_pages(path: str | Path) -> Iterator[Page]:
    """Entrega uma página por vez; PDFs são convertidos em Markdown sob demanda."""
    path = Path(path)
    info = inspect_document(path)
    yield from _pages(path, info.file_type)


def load_document(path: str | Path) -> Document:
    """Documento completo em memória; para arquivos pequenos e testes."""
    path = Path(path)
    info = inspect_document(path)
    return Document(info.filename, info.file_type, info.sha256, list(_pages(path, info.file_type)))
