"""Configuração da aplicação via variáveis de ambiente (.env).

F1: campos de transporte (host/porta/TLS) — ver F1_FastAPI_MCP_Server_Setup.md §7.
F2: campos de conexão do Config DB — ver F2_POSTGRESQL_ADAPTER.md §7.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
