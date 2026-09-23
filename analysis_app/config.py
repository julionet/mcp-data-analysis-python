"""Configuração da aplicação via variáveis de ambiente (.env).

F1: apenas os campos de transporte (host/porta/TLS) — ver F1_FastAPI_MCP_Server_Setup.md §7.
Campos de banco de dados, cache etc. entram a partir de F2.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    server_host: str = "0.0.0.0"
    server_port: int = 3000
    tls_cert_file: str = "certs/server.pem"
    tls_key_file: str = "certs/server-key.pem"


settings = Settings()
