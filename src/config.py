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
F14: QUERY_RETRY_MAX_ATTEMPTS / QUERY_RETRY_BACKOFF_BASE_MS — retry só de falha rápida
    de conexão ao data source (F14_ERROR_HANDLING_VALIDATION.md §4.3, §7).
F15: PG_POOL_MIN/MAX_SIZE e CONFIG_DB_POOL_MIN/MAX_SIZE — tamanho do pool PostgreSQL
    (F15_PERFORMANCE_OPTIMIZATION.md §4.3, §7). Falha no startup se MIN < 1 ou MAX < MIN.
F16: DOCS_ENABLED — liga /docs, /redoc e /openapi.json (Swagger) só em ambiente local;
    padrão false (F16_API_DOCUMENTATION.md §4.2).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_CACHE_BACKENDS = {"memory", "none"}


class Settings(BaseSettings):
    # extra="ignore": o .env é único (host + compose) e traz variáveis que só o compose usa
    # (POSTGRES_HOST_PORT, NGINX_*, e as dos bancos opcionais MYSQL_*/MSSQL_*/ORACLE_*); sem isso o pydantic-settings as rejeita.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    server_host: str = "0.0.0.0"
    server_port: int = 3000
    tls_enabled: bool = True  # False só em desenvolvimento local (HTTP puro)
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
    query_retry_max_attempts: int = 3  # total de tentativas (1 = sem retry) — F14
    query_retry_backoff_base_ms: int = 200  # espera = base * 2^(tentativa-1) — F14

    # F15: pool PostgreSQL — data sources (PG_POOL_*) e Config DB (CONFIG_DB_POOL_*) separados.
    # Padrão 10/10 = o default anterior do asyncpg (sem mudança em instalações existentes).
    pg_pool_min_size: int = 10
    pg_pool_max_size: int = 10
    config_db_pool_min_size: int = 10
    config_db_pool_max_size: int = 10

    fernet_key: str

    docs_enabled: bool = False  # F16: Swagger (/docs, /redoc, /openapi.json) — só em ambiente local

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
        if self.query_retry_max_attempts < 1:
            raise ValueError("QUERY_RETRY_MAX_ATTEMPTS deve ser >= 1 (1 = sem retry)")
        if self.query_retry_backoff_base_ms < 0:
            raise ValueError("QUERY_RETRY_BACKOFF_BASE_MS deve ser >= 0")
        for prefix, low, high in (
            ("PG_POOL", self.pg_pool_min_size, self.pg_pool_max_size),
            ("CONFIG_DB_POOL", self.config_db_pool_min_size, self.config_db_pool_max_size),
        ):
            if low < 1:
                raise ValueError(f"{prefix}_MIN_SIZE deve ser >= 1")
            if high < low:
                raise ValueError(f"{prefix}_MAX_SIZE não pode ser menor que {prefix}_MIN_SIZE")
        if self.access_token_expiration_days < 1 or self.access_token_max_expiration_days < 1:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRATION_DAYS e ACCESS_TOKEN_MAX_EXPIRATION_DAYS devem ser >= 1"
            )
        if self.access_token_expiration_days > self.access_token_max_expiration_days:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRATION_DAYS não pode ser maior que ACCESS_TOKEN_MAX_EXPIRATION_DAYS"
            )


settings = Settings()
