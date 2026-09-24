"""Exceções de domínio compartilhadas — F3_CONTROLE_VOLUME.md §4.4, F4_EXECUTION_ENGINE.md §4.4."""


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
    def __init__(self, analysis_id) -> None:
        self.analysis_id = analysis_id
        super().__init__(f"Análise '{analysis_id}' não encontrada ou inativa")


class InvalidAnalysisSchemaError(Exception):
    """Erro de configuração — quem cadastrou analyses.parameters errou, não o cliente."""


class InvalidParametersError(Exception):
    """Parâmetros enviados pelo cliente não batem com analyses.parameters."""


class DataSourceConnectionError(Exception):
    """Erro de conexão/SQL no data source — mensagem sem stack trace nem credenciais."""
