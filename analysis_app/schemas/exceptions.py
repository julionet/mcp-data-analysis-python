"""Exceções de domínio compartilhadas — F3_CONTROLE_VOLUME.md §4.4."""


class VolumeExceededError(Exception):
    def __init__(
        self,
        estimated_rows: int | None = None,
        estimated_size_kb: float | None = None,
    ) -> None:
        self.estimated_rows = estimated_rows
        self.estimated_size_kb = estimated_size_kb
        super().__init__("Volume de resultado excede o limite configurado")
