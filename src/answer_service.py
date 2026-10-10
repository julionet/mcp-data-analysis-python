import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from src import config
from src.generation import NOT_FOUND_ANSWER
from src.retrieval import FETCH_K, TOP_K, SearchHit
from src.search_service import SearchOutcome, run_search


class AskError(Exception):
    """Erro esperado, com mensagem já pronta para a pessoa."""


@dataclass(frozen=True)
class AskOutcome:
    search: SearchOutcome
    answer: str | None = None  # None quando a busca parou antes (base vazia, pasta sem documentos)
    sources: list[tuple[int, SearchHit]] = field(default_factory=list)  # (número em [n], trecho) citados
    truncated: bool = False
    cited_none: bool = False  # resposta com informação e nenhum [n] (T7)
    answer_elapsed: float = 0.0


_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def extract_cited(text: str, total: int) -> list[int]:
    """Números citados como [n], [n][m] ou [n, m], só de 1 a total, sem repetição e em ordem (T5)."""
    numbers = {int(n) for group in _CITATION.findall(text) for n in re.findall(r"\d+", group)}
    return sorted(n for n in numbers if 1 <= n <= total)


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def is_not_found(text: str) -> bool:
    return _normalize(text).startswith(_normalize(NOT_FOUND_ANSWER))  # o Claude pode explicar depois da frase


def run_ask(
    text: str,
    method: str = "rrf",
    top_k: int = TOP_K,
    fetch_k: int = FETCH_K,
    folder: str | None = None,
    before_send: Callable[[SearchOutcome], None] | None = None,
) -> AskOutcome:
    """Fluxo da seção 4.1 da F07: configuração, busca (F06), chamada ao Claude e fontes citadas."""
    if not text.strip():
        raise AskError("Informe a pergunta.")
    for name in ("ANTHROPIC_API_KEY", "LLM_MODEL"):  # antes da busca, que pode carregar o modelo (T1)
        if not getattr(config, name):
            raise AskError(f"{name} não definida. Copie .env.example para .env e preencha.")

    search = run_search(text, method, top_k, fetch_k, folder)
    if search.status != "ok":
        return AskOutcome(search)
    if not search.hits:
        return AskOutcome(search, NOT_FOUND_ANSWER)  # T3: sem chamar o Claude

    from src.generation import Generator  # importa o SDK só quando vai chamar o Claude

    generator = Generator()
    if before_send:
        before_send(search)
    started = time.perf_counter()
    generated = generator.answer_hits(text.strip(), search.hits)
    elapsed = time.perf_counter() - started

    if is_not_found(generated.text):
        return AskOutcome(search, generated.text, [], generated.truncated, False, elapsed)  # T6
    cited = extract_cited(generated.text, len(search.hits))
    sources = [(n, search.hits[n - 1]) for n in cited]
    return AskOutcome(search, generated.text, sources, generated.truncated, not cited, elapsed)
