"""Exceções de domínio compartilhadas — F3_CONTROLE_VOLUME.md §4.4, F4_EXECUTION_ENGINE.md §4.4.

F14 (F14_ERROR_HANDLING_VALIDATION.md §4.2): cada exceção que vira {"status": "error"} traz
`error_code` (conjunto fechado) e `retryable` (se o cliente pode tentar de novo) como
atributos de classe; error_info() lê os dois sem if/elif por tipo.
"""

INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


class VolumeExceededError(Exception):
    def __init__(
        self,
        estimated_rows: int | None = None,
        estimated_size_kb: float | None = None,
    ) -> None:
        self.estimated_rows = estimated_rows
        self.estimated_size_kb = estimated_size_kb
        super().__init__("Volume de resultado excede o limite configurado")


class AnalysisNotFoundError(Exception):
    """Também cobre "sem permissão" em call_tool() — F14 decisão 6: mesma resposta."""

    error_code = "ANALYSIS_NOT_FOUND"
    retryable = False

    def __init__(self, analysis_id) -> None:
        self.analysis_id = analysis_id
        super().__init__(f"Análise '{analysis_id}' não encontrada ou inativa")


class InvalidAnalysisSchemaError(Exception):
    """Erro de configuração — quem cadastrou a análise errou (analyses.parameters, steps
    ausentes ou SQL que não é um SELECT), não o cliente."""

    error_code = "INVALID_ANALYSIS_CONFIG"
    retryable = False


class InvalidParametersError(Exception):
    """Parâmetros enviados pelo cliente não batem com analyses.parameters."""

    error_code = "INVALID_PARAMETERS"
    retryable = False


class DataSourceConnectionError(Exception):
    """Erro de conexão/SQL no data source — mensagem sem stack trace nem credenciais.

    F14: base das duas subclasses abaixo (os `except DataSourceConnectionError`
    existentes continuam valendo). Usada diretamente para conexão indisponível."""

    error_code = "DATA_SOURCE_UNAVAILABLE"
    retryable = True


class QueryTimeoutError(DataSourceConnectionError):
    """A query excedeu QUERY_TIMEOUT_SECONDS. Sem retry no servidor (F14 decisão 8):
    o cliente decide repetir, de preferência com um filtro mais estreito."""

    error_code = "QUERY_TIMEOUT"
    retryable = True


class QueryExecutionError(DataSourceConnectionError):
    """O banco rejeitou/falhou a execução do SQL (não é conexão nem timeout)."""

    error_code = "QUERY_FAILED"
    retryable = False


class InvalidCacheFrequencyError(Exception):
    """analyses.cache_frequency não é um dos valores aceitos (hourly/daily/weekly/none)."""

    error_code = "INVALID_ANALYSIS_CONFIG"
    retryable = False


def error_response(message: str, error_code: str, retryable: bool) -> dict:
    """Resposta de erro do contrato F14 (F14_ERROR_HANDLING_VALIDATION.md §4.2) — usada por
    AnalysisService.execute() e por mcp_transport/tools.py::call_tool()."""
    return {
        "status": "error",
        "error_code": error_code,
        "retryable": retryable,
        "mensagem": message,
        "cached": False,
    }


def error_info(exc: BaseException) -> tuple[str, bool]:
    """(error_code, retryable) de uma exceção; qualquer tipo desconhecido é INTERNAL_ERROR."""
    return getattr(exc, "error_code", INTERNAL_ERROR_CODE), getattr(exc, "retryable", False)
