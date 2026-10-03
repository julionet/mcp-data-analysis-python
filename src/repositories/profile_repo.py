"""Permissões usuário → perfil → analyses — F12_AUTENTICACAO_PERFIS.md §4.4."""

from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter


class ProfileRepository:
    def __init__(self, config_db_adapter: PostgreSQLAdapter) -> None:
        self._db = config_db_adapter

    async def get_allowed_analysis_ids(self, user_id: UUID) -> set[UUID]:
        """Mesma regra de AnalysisRepository.get_allowed_for_user(): analyses ativas
        vinculadas a um perfil ativo vinculado ao usuário. Usado só pela
        revalidação de call_tool() (AuthService.is_analysis_allowed)."""
        rows = await self._db.execute_query(
            "SELECT DISTINCT a.id "
            "FROM analyses a "
            "JOIN profile_analyses pa ON pa.analysis_id = a.id "
            "JOIN user_profiles up ON up.profile_id = pa.profile_id "
            "JOIN profiles p ON p.id = pa.profile_id "
            "WHERE up.user_id = $1 AND a.is_active = true AND p.is_active = true",
            {"user_id": user_id},
        )
        return {row["id"] for row in rows}
