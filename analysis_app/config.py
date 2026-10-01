"""Configuração da aplicação via variáveis de ambiente (.env).

F1: campos de transporte (host/porta/TLS) — ver F1_FastAPI_MCP_Server_Setup.md §7.
F2: campos de conexão do Config DB — ver F2_POSTGRESQL_ADAPTER.md §7.
F3: limites do Controle de Volume — ver F3_CONTROLE_VOLUME.md §7.
F4 (ajuste retroativo, 2026-09-26): query_timeout_seconds — timeout de query no
    Postgres (RNF2/§8.1 ARQUITETURA.md), antes ausente — ver F4_EXECUTION_ENGINE.md.
F4: FERNET_KEY passa a ser efetivamente usada por security/crypto.py — ver F4_EXECUTION_ENGINE.md §7.
F7: CACHE_BACKEND, CACHE_MAX_ENTRIES, CACHE_MAX_SIZE_MB — ver F7_CACHE_SERVICE.md §7.
    CACHE_BACKEND só aceita "memory" ou "none" em V1.0; outro valor falha no
    startup (validado aqui, não pelo pydantic-settings, para dar uma mensagem
    clara). "none" (ajuste retroativo, 2026-09-27) é o kill-switch global de
    cache — desliga para todas as análises sem tocar em cache_frequency.
F12: ACCESS_TOKEN_EXPIRATION_DAYS / ACCESS_TOKEN_MAX_EXPIRATION_DAYS — validade
    padrão e máxima dos tokens emitidos por POST /auth/token. Falha no startup se
    algum for < 1 ou se EXPIRATION > MAX (senão a emissão com o padrão já daria 400).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_CACHE_BACKENDS = {"memory", "none"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    server_host: str = "0.0.0.0"
    server_port: int = 3000
    tls_cert_file: str = "certs/server.pem"
    tls_key_file: str = "certs/server-key.pem"

    postgres_config_host: str
    postgres_config_port: int = 5432
    postgres_config_user: str
    postgres_config_password: str
    postgres_config_database: str

    default_max_result_rows: int = 500
    default_max_result_size_kb: int = 150
    query_timeout_seconds: int = 30

    fernet_key: str

    cache_backend: str = "memory"
    cache_max_entries: int = 200
    cache_max_size_mb: int = 100

    access_token_expiration_days: int = 90
    access_token_max_expiration_days: int = 365

    def model_post_init(self, __context) -> None:
        if self.cache_backend not in _VALID_CACHE_BACKENDS:
            raise ValueError(
                f"CACHE_BACKEND '{self.cache_backend}' inválido — "
                f"valores aceitos: {', '.join(_VALID_CACHE_BACKENDS)}"
            )
        if self.access_token_expiration_days < 1 or self.access_token_max_expiration_days < 1:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRATION_DAYS e ACCESS_TOKEN_MAX_EXPIRATION_DAYS devem ser >= 1"
            )
        if self.access_token_expiration_days > self.access_token_max_expiration_days:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRATION_DAYS não pode ser maior que ACCESS_TOKEN_MAX_EXPIRATION_DAYS"
            )


settings = Settings()
