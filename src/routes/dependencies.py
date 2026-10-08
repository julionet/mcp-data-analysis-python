"""Dependências FastAPI da API administrativa — F23 §4.3.

Os serviços são montados sobre `config_db_adapter` (sem importar `mcp_transport.tools`);
os testes de rota os trocam por `app.dependency_overrides`. Imports tardios: não puxam
o Config DB ao importar este módulo.
"""

from repositories.user_repo import UserRepository
from services.profile_admin_service import ProfileAdminService
from services.user_admin_service import UserAdminService


def get_user_repo() -> UserRepository:
    from database.connection import config_db_adapter

    return UserRepository(config_db_adapter)


def get_user_admin_service() -> UserAdminService:
    from database.connection import config_db_adapter
    from repositories.access_token_repo import AccessTokenRepository

    return UserAdminService(
        config_db_adapter, UserRepository(config_db_adapter), AccessTokenRepository(config_db_adapter)
    )


def get_profile_admin_service() -> ProfileAdminService:
    from database.connection import config_db_adapter
    from repositories.profile_repo import ProfileRepository

    return ProfileAdminService(config_db_adapter, ProfileRepository(config_db_adapter))
