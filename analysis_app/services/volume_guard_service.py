"""Controle de Volume de Resultado — F3_CONTROLE_VOLUME.md §4.4, ARQUITETURA.md §3.4/§4.3."""

import json

from schemas.exceptions import VolumeExceededError


class VolumeGuardService:
    def __init__(self, max_rows: int, max_size_kb: int) -> None:
        self.max_rows = max_rows
        self.max_size_kb = max_size_kb

    async def check_row_count(self, adapter, count_sql: str, params: dict) -> int:
        """Executa COUNT(*) barato; levanta VolumeExceededError se exceder o limite."""
        count = await adapter.execute_query(count_sql, params, scalar=True)
        if count > self.max_rows:
            raise VolumeExceededError(estimated_rows=count)
        return count

    def check_serialized_size(self, result: list[dict]) -> float:
        """Mede o resultado já serializado em KB; levanta VolumeExceededError se exceder."""
        size_kb = len(json.dumps(result).encode("utf-8")) / 1024
        if size_kb > self.max_size_kb:
            raise VolumeExceededError(estimated_size_kb=size_kb)
        return size_kb

    def build_refinement_response(self, error: VolumeExceededError) -> dict:
        """Monta o payload estruturado de recusa (status volume_exceeded)."""
        return {
            "status": "volume_exceeded",
            "estimativa": {
                "linhas": error.estimated_rows,
                "tamanho_estimado_kb": error.estimated_size_kb,
            },
            "limite": {"linhas": self.max_rows, "tamanho_kb": self.max_size_kb},
            "mensagem": (
                f"Sua consulta retornaria aproximadamente {error.estimated_rows} linhas "
                f"(~{error.estimated_size_kb}KB), acima do limite de {self.max_rows} linhas / "
                f"{self.max_size_kb}KB. Refine o período ou adicione filtros (ex: região, produto). "
                f"Se quiser continuar mesmo assim, chame novamente com confirmar_volume_alto=true — "
                f"atenção: isso pode consumir um volume alto de tokens."
            ),
        }
