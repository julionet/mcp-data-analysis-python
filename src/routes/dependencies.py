"""Dependências FastAPI da API administrativa — F23 §4.3.

Os serviços são montados sobre `config_db_adapter` (sem importar `mcp_transport.tools`);
os testes de rota os trocam por `app.dependency_overrides`. Imports tardios: não puxam
o Config DB ao importar este módulo.
"""

from repositories.user_repo import UserRepository
from services.analysis_admin_service import AnalysisAdminService
from services.data_source_admin_service import DataSourceAdminService
from services.execution_admin_service import ExecutionAdminService
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


def get_data_source_admin_service() -> DataSourceAdminService:
    # Import tardio: o singleton `analysis_service` (dono do pool de adapters) só é
    # necessário para invalidá-lo ao editar/desativar/excluir um data source (F24 §4.3).
    from database.connection import config_db_adapter
    from mcp_transport.tools import analysis_service
    from repositories.data_source_repo import DataSourceRepository

    return DataSourceAdminService(
        config_db_adapter,
        DataSourceRepository(config_db_adapter),
        analysis_service,
        UserRepository(config_db_adapter),
    )


def get_analysis_admin_service() -> AnalysisAdminService:
    from database.connection import config_db_adapter
    from repositories.analysis_repo import AnalysisRepository
    from repositories.data_source_repo import DataSourceRepository
    from repositories.profile_repo import ProfileRepository

    return AnalysisAdminService(
        config_db_adapter,
        AnalysisRepository(config_db_adapter),
        DataSourceRepository(config_db_adapter),
        ProfileRepository(config_db_adapter),
        UserRepository(config_db_adapter),
    )


def get_execution_admin_service() -> ExecutionAdminService:
    from database.connection import config_db_adapter
    from repositories.analysis_repo import AnalysisRepository
    from repositories.execution_repo import ExecutionRepository

    return ExecutionAdminService(
        ExecutionRepository(config_db_adapter), AnalysisRepository(config_db_adapter)
    )
