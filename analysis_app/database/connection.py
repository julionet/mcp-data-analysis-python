"""Pool de conexão do Config DB (analysis_config) — F2_POSTGRESQL_ADAPTER.md §4.2.

Usado no startup do FastAPI (main.py) e pelo /health.
"""

import logging

from adapters.postgresql import PostgreSQLAdapter
from config import settings

logger = logging.getLogger(__name__)

config_db_adapter = PostgreSQLAdapter(
    {
        "host": settings.postgres_config_host,
        "port": settings.postgres_config_port,
        "user": settings.postgres_config_user,
        "password": settings.postgres_config_password,
        "database": settings.postgres_config_database,
    }
)


async def connect_config_db() -> None:
    try:
        await config_db_adapter.connect()
    except Exception:
        logger.error(
            "Falha ao conectar ao Config DB em %s:%s/%s (user=%s) — aplicação não vai subir.",
            settings.postgres_config_host,
            settings.postgres_config_port,
            settings.postgres_config_database,
            settings.postgres_config_user,
        )
        raise


async def disconnect_config_db() -> None:
    await config_db_adapter.disconnect()


async def check_postgres() -> bool:
    return await config_db_adapter.test_connection()
