"""Repositórios do Config DB sem banco — SQL, ordem dos valores ligados e mapeamento (F17, decisão 10).

O adapter liga o dict de parâmetros por POSIÇÃO (`$1…$n` ← `*params.values()`): o erro mais caro
de um repositório é trocar a ordem. Estes testes capturam a consulta e os valores com um adapter
simulado (padrão de `TestExecutionQueries`, F25); que o SQL roda de verdade é papel dos testes
`integration`.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from repositories.access_token_repo import AccessTokenRepository
from repositories.analysis_repo import AnalysisRepository
from repositories.data_source_repo import DataSourceRepository
from repositories.profile_repo import ProfileRepository
from repositories.sql_helpers import like_pattern, set_clause
from repositories.user_repo import UserRepository


def make_db(result=None):
    db = AsyncMock()
    db.execute_query.return_value = [] if result is None else result
    return db


def q(db):
    """(query, lista de valores ligados, kwargs) da última execute_query."""
    call = db.execute_query.await_args
    params = call.args[1] if len(call.args) > 1 else {}
    return call.args[0], list((params or {}).values()), call.kwargs


def ex(db, index=-1):
    """(query, args posicionais) de uma chamada a execute()."""
    call = db.execute.await_args_list[index]
    return call.args[0], list(call.args[1:])


class TestSqlHelpers:
    def test_like_pattern_escapes_wildcards_and_backslash(self):
        assert like_pattern("50%_\\x") == "%50\\%\\_\\\\x%"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_like_pattern_empty_means_no_filter(self, empty):
        assert like_pattern(empty) is None

    def test_set_clause_numbers_placeholders_from_the_given_index(self):
        assert set_clause({"name": "x", "is_admin": True}, 2) == "name = $2, is_admin = $3"
        assert set_clause({"a": 1}) == "a = $1"


class TestAccessTokenRepository:
    ROW = dict(id=uuid4(), user_id=uuid4(), token_hash="h", label="cli",
               expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc), revoked_at=None)

    @pytest.mark.asyncio
    async def test_get_by_hash_maps_row_or_none(self):
        db = make_db([self.ROW])
        token = await AccessTokenRepository(db).get_by_hash("h")

        query, values, _ = q(db)
        assert "WHERE token_hash = $1" in query and values == ["h"]
        assert (token.id, token.user_id, token.label, token.revoked_at) == (
            self.ROW["id"], self.ROW["user_id"], "cli", None)
        db.execute_query.return_value = []
        assert await AccessTokenRepository(db).get_by_hash("x") is None

    @pytest.mark.asyncio
    async def test_create_binds_user_hash_expiry_label_in_order(self):
        db = make_db([self.ROW])
        uid, exp = uuid4(), datetime(2030, 1, 1, tzinfo=timezone.utc)

        token = await AccessTokenRepository(db).create(uid, "hash", exp, "meu")

        query, values, _ = q(db)
        assert "INSERT INTO access_tokens (user_id, token_hash, expires_at, label)" in query
        assert "RETURNING" in query and values == [uid, "hash", exp, "meu"] and token.token_hash == "h"

    @pytest.mark.asyncio
    async def test_touch_and_revoke_are_idempotent_updates(self):
        db, tid = make_db(), uuid4()
        repo = AccessTokenRepository(db)

        await repo.touch_last_used(tid)
        assert ex(db) == ("UPDATE access_tokens SET last_used_at = NOW() WHERE id = $1", [tid])
        await repo.revoke(tid)
        query, args = ex(db)
        assert "revoked_at IS NULL" in query and args == [tid]  # mantém o revoked_at original

    @pytest.mark.asyncio
    async def test_list_by_user_never_selects_the_token_hash(self):
        db, uid = make_db([{"id": 1}]), uuid4()

        rows = await AccessTokenRepository(db).list_by_user(uid)

        query, values, _ = q(db)
        assert "token_hash" not in query and "ORDER BY created_at DESC" in query
        assert values == [uid] and rows == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_count_active_filters_revoked_and_expired(self):
        db, uid = make_db(3), uuid4()

        assert await AccessTokenRepository(db).count_active(uid) == 3

        query, values, kwargs = q(db)
        assert "revoked_at IS NULL AND expires_at > NOW()" in query
        assert values == [uid] and kwargs == {"scalar": True}

    @pytest.mark.asyncio
    async def test_revoke_for_user_requires_matching_owner(self):
        tid, uid = uuid4(), uuid4()
        db = make_db([{"id": tid}])
        assert await AccessTokenRepository(db).revoke_for_user(tid, uid) is True
        query, values, _ = q(db)
        assert "WHERE id = $1 AND user_id = $2" in query and "COALESCE(revoked_at, NOW())" in query
        assert values == [tid, uid]
        db.execute_query.return_value = []
        assert await AccessTokenRepository(db).revoke_for_user(tid, uid) is False

    @pytest.mark.asyncio
    async def test_revoke_all_counts_rows_and_accepts_a_transaction(self):
        tx, uid = make_db([{"id": 1}, {"id": 2}]), uuid4()
        adapter = make_db()

        assert await AccessTokenRepository(adapter).revoke_all(uid, tx) == 2

        adapter.execute_query.assert_not_awaited()  # usou a transação, não o adapter
        query, values, _ = q(tx)
        assert "revoked_at IS NULL" in query and values == [uid]


class TestUserRepository:
    ROW = dict(id=uuid4(), name="Maria", external_id="m@x.com", password_hash="h", is_blocked=False, is_admin=True)

    @pytest.mark.asyncio
    async def test_get_by_id_and_external_id_map_to_user(self):
        db = make_db([self.ROW])
        repo = UserRepository(db)

        by_id = await repo.get_by_id(self.ROW["id"])
        assert "WHERE id = $1" in q(db)[0] and by_id.is_admin is True and by_id.external_id == "m@x.com"
        by_email = await repo.get_by_external_id("m@x.com")
        assert "WHERE external_id = $1" in q(db)[0] and q(db)[1] == ["m@x.com"] and by_email.name == "Maria"
        db.execute_query.return_value = []
        assert await repo.get_by_id(uuid4()) is None and await repo.get_by_external_id("n") is None

    @pytest.mark.asyncio
    async def test_list_page_binds_three_filters_then_limit_offset(self):
        db = make_db()
        db.execute_query.side_effect = [7, [{"id": 1}]]
        pid = uuid4()

        rows, total = await UserRepository(db).list_page("50%", True, pid, 20, 40)

        count_call = db.execute_query.await_args_list[0]
        count_q, count_values, count_kw = count_call.args[0], list(count_call.args[1].values()), count_call.kwargs
        assert "COUNT(*) FROM users u" in count_q and count_kw == {"scalar": True}
        assert count_values == ["%50\\%%", True, pid]
        query, values, _ = q(db)
        assert "ORDER BY u.name, u.id LIMIT $4 OFFSET $5" in query and "password_hash" not in query
        assert values == ["%50\\%%", True, pid, 20, 40] and (rows, total) == ([{"id": 1}], 7)

    @pytest.mark.asyncio
    async def test_list_page_without_filters_binds_nulls(self):
        db = make_db()
        db.execute_query.side_effect = [0, []]

        await UserRepository(db).list_page(None, None, None, 50, 0)

        assert q(db)[1] == [None, None, None, 50, 0]

    @pytest.mark.asyncio
    async def test_get_admin_row_excludes_password_hash(self):
        db = make_db([{"id": 1}])
        repo = UserRepository(db)

        assert await repo.get_admin_row(uuid4()) == {"id": 1}
        assert "password_hash" not in q(db)[0]
        db.execute_query.return_value = []
        assert await repo.get_admin_row(uuid4()) is None

    @pytest.mark.asyncio
    async def test_create_binds_in_column_order_and_returns_id(self):
        new_id = uuid4()
        db = make_db(new_id)

        got = await UserRepository(db).create("Ana", "a@x.com", "hash", True, "admin", None)

        query, values, kwargs = q(db)
        assert got == new_id and kwargs == {"scalar": True}
        assert "(name, external_id, password_hash, is_admin, created_by)" in query
        assert values == ["Ana", "a@x.com", "hash", True, "admin"]

    @pytest.mark.asyncio
    async def test_update_builds_set_clause_and_always_touches_updated_at(self):
        uid = uuid4()
        db = make_db([{"id": uid}])

        assert await UserRepository(db).update(uid, {"name": "N", "is_admin": False}) is True

        query, values, _ = q(db)
        assert "SET name = $2, is_admin = $3, updated_at = NOW() WHERE id = $1" in query
        assert values == [uid, "N", False]
        db.execute_query.return_value = []
        assert await UserRepository(db).update(uid, {"name": "N"}) is False

    @pytest.mark.asyncio
    async def test_delete_has_history_and_lock_admins(self):
        uid, aid = uuid4(), uuid4()
        db = make_db([{"id": uid}])
        repo = UserRepository(db)

        assert await repo.delete(uid) is True
        db.execute_query.return_value = [{"x": 1}]
        assert await repo.has_history(uid) is True
        assert "FROM execution_history WHERE user_id = $1 LIMIT 1" in q(db)[0]
        db.execute_query.return_value = [{"id": aid}]
        assert await repo.lock_active_admin_ids(db) == {aid}
        assert "is_admin AND NOT is_blocked FOR UPDATE" in q(db)[0]

    @pytest.mark.asyncio
    async def test_profiles_queries_and_replace_semantics(self):
        uid, p1, p2 = uuid4(), uuid4(), uuid4()
        db = make_db([{"id": p1}])
        repo = UserRepository(db)

        assert await repo.existing_profile_ids([p1, p2], None) == {p1}
        assert "id = ANY($1::uuid[])" in q(db)[0] and q(db)[1] == [[p1, p2]]
        await repo.get_profiles(uid)
        assert "JOIN user_profiles up" in q(db)[0] and q(db)[1] == [uid]

        tx = make_db()
        await repo.replace_profiles(uid, [p1, p2], tx)
        assert tx.execute.await_count == 2
        assert ex(tx, 0) == ("DELETE FROM user_profiles WHERE user_id = $1", [uid])
        assert ex(tx, 1)[1] == [uid, [p1, p2]] and "UNNEST($2::uuid[])" in ex(tx, 1)[0]

        empty_tx = make_db()
        await repo.replace_profiles(uid, [], empty_tx)
        assert empty_tx.execute.await_count == 1  # só o DELETE: lista vazia limpa os vínculos


class TestProfileRepository:
    @pytest.mark.asyncio
    async def test_get_allowed_analysis_ids_same_rule_as_listing(self):
        aid, uid = uuid4(), uuid4()
        db = make_db([{"id": aid}, {"id": aid}])

        assert await ProfileRepository(db).get_allowed_analysis_ids(uid) == {aid}

        query, values, _ = q(db)
        assert "a.is_active = true AND p.is_active = true" in query and values == [uid]

    @pytest.mark.asyncio
    async def test_list_page_filters_then_limit_offset(self):
        db = make_db()
        db.execute_query.side_effect = [4, [{"id": 1}]]

        rows, total = await ProfileRepository(db).list_page("com", False, 10, 5)

        assert db.execute_query.await_args_list[0].kwargs == {"scalar": True}
        query, values, _ = q(db)
        assert "ORDER BY p.name, p.id LIMIT $3 OFFSET $4" in query and "users_count" in query
        assert values == ["%com%", False, 10, 5] and (rows, total) == ([{"id": 1}], 4)

    @pytest.mark.asyncio
    async def test_summary_create_update_delete(self):
        pid = uuid4()
        db = make_db([{"id": pid}])
        repo = ProfileRepository(db)

        assert await repo.get_summary(pid) == {"id": pid}
        db.execute_query.return_value = []
        assert await repo.get_summary(pid) is None

        db.execute_query.return_value = pid
        assert await repo.create("Comercial", None, True) == pid
        query, values, _ = q(db)
        assert "(name, description, is_active)" in query and values == ["Comercial", None, True]

        db.execute_query.return_value = [{"id": pid}]
        assert await repo.update(pid, {"description": None, "is_active": False}) is True
        query, values, _ = q(db)
        assert "SET description = $2, is_active = $3, updated_at = NOW() WHERE id = $1" in query
        assert values == [pid, None, False]
        assert await repo.delete(pid) is True
        db.execute_query.return_value = []
        assert await repo.update(pid, {"name": "x"}) is False and await repo.delete(pid) is False

    @pytest.mark.asyncio
    async def test_members_and_existing_ids(self):
        pid, x = uuid4(), uuid4()
        db = make_db([{"id": x}])
        repo = ProfileRepository(db)

        await repo.get_users(pid)
        assert "u.external_id AS email" in q(db)[0] and "password_hash" not in q(db)[0] and q(db)[1] == [pid]
        await repo.get_analyses(pid)
        assert "JOIN profile_analyses pa" in q(db)[0] and q(db)[1] == [pid]
        for table in ("users", "analyses", "profiles"):
            assert await repo.existing_ids(table, [x]) == {x}
            assert f"FROM {table} WHERE id = ANY($1::uuid[])" in q(db)[0]
        with pytest.raises(AssertionError):
            await repo.existing_ids("access_tokens", [x])  # tabela fora da lista fixa

    @pytest.mark.asyncio
    async def test_replace_analyses_and_users_delete_then_insert_unless_empty(self):
        pid, ids = uuid4(), [uuid4(), uuid4()]
        repo = ProfileRepository(make_db())

        for method, table, column in (
            (repo.replace_analyses, "profile_analyses", "analysis_id"),
            (repo.replace_users, "user_profiles", "user_id"),
        ):
            tx = make_db()
            await method(pid, ids, tx)
            assert ex(tx, 0) == (f"DELETE FROM {table} WHERE profile_id = $1", [pid])
            query, args = ex(tx, 1)
            assert f"INSERT INTO {table} (profile_id, {column})" in query and args == [pid, ids]
            empty = make_db()
            await method(pid, [], empty)
            assert empty.execute.await_count == 1


class TestAnalysisRepository:
    PARAMS = {"a": {"type": "integer"}}
    ROW = dict(id=uuid4(), name="vendas", description="d", data_source_id=uuid4(), parameters=json.dumps(PARAMS),
               is_active=True, updated_at=datetime(2026, 1, 1), cache_frequency="daily")

    @pytest.mark.asyncio
    async def test_readers_decode_json_and_filter_as_documented(self):
        db = make_db([dict(self.ROW)])
        repo = AnalysisRepository(db)

        by_id = await repo.get_by_id(self.ROW["id"])
        assert "id = $1 AND is_active = true" in q(db)[0] and by_id.parameters == self.PARAMS
        by_name = await repo.get_by_name("vendas")
        assert "WHERE name = $1" in q(db)[0] and "is_active" not in q(db)[0].split("WHERE")[1]
        assert by_name.cache_frequency == "daily"
        assert [a.name for a in await repo.get_all()] == ["vendas"]
        assert "WHERE is_active = true" in q(db)[0]
        uid = uuid4()
        allowed = await repo.get_allowed_for_user(uid)
        assert q(db)[1] == [uid] and "p.is_active = true" in q(db)[0] and len(allowed) == 1

        db.execute_query.return_value = []
        assert await repo.get_by_id(uuid4()) is None and await repo.get_by_name("x") is None

    @pytest.mark.asyncio
    async def test_null_parameters_become_empty_dict(self):
        db = make_db([{**self.ROW, "parameters": None}])

        assert (await AnalysisRepository(db).get_by_id(self.ROW["id"])).parameters == {}

    @pytest.mark.asyncio
    async def test_get_steps_decodes_definition(self):
        row = dict(id=uuid4(), analysis_id=uuid4(), step_order=1, step_type="query",
                   definition=json.dumps({"sql": "SELECT 1", "params": []}))
        db = make_db([row])

        steps = await AnalysisRepository(db).get_steps(row["analysis_id"])

        assert "ORDER BY step_order" in q(db)[0] and steps[0].definition == {"sql": "SELECT 1", "params": []}

    @pytest.mark.asyncio
    async def test_admin_list_includes_inactive_and_binds_filters(self):
        db = make_db()
        db.execute_query.side_effect = [3, [{"id": 1}]]
        ds = uuid4()

        rows, total = await AnalysisRepository(db).admin_list("v_", ds, None, 10, 20)

        query, values, _ = q(db)
        assert "ORDER BY a.name, a.id LIMIT $4 OFFSET $5" in query
        assert values == ["%v\\_%", ds, None, 10, 20] and (rows, total) == ([{"id": 1}], 3)

    @pytest.mark.asyncio
    async def test_get_admin_row_decodes_parameters_and_misses(self):
        db = make_db([{"id": 1, "parameters": json.dumps(self.PARAMS)}])
        repo = AnalysisRepository(db)

        assert (await repo.get_admin_row(uuid4()))["parameters"] == self.PARAMS
        db.execute_query.return_value = [{"id": 1, "parameters": None}]
        assert (await repo.get_admin_row(uuid4()))["parameters"] == {}
        db.execute_query.return_value = []
        assert await repo.get_admin_row(uuid4()) is None

    @pytest.mark.asyncio
    async def test_create_and_steps_serialize_jsonb(self):
        new_id, aid = uuid4(), uuid4()
        db = make_db(new_id)
        repo = AnalysisRepository(db)
        fields = dict(name="n", description=None, data_source_id=uuid4(), cache_frequency="daily",
                      parameters=self.PARAMS, is_active=True, created_by="admin")

        assert await repo.create(fields) == new_id
        query, values, _ = q(db)
        assert "$5::jsonb" in query and values[4] == json.dumps(self.PARAMS)
        assert values[:4] == ["n", None, fields["data_source_id"], "daily"] and values[5:] == [True, "admin"]

        await repo.create_step(aid, {"sql": "SELECT 1", "params": []})
        query, values, _ = q(db)
        assert "step_order, step_type, definition" in query and "1, 'query', $2::jsonb" in query
        assert values == [aid, json.dumps({"sql": "SELECT 1", "params": []})]
        sid = uuid4()
        await repo.update_step(sid, {"sql": "SELECT 2", "params": []})
        query, values, _ = q(db)
        assert "updated_at = NOW()" in query and values == [sid, json.dumps({"sql": "SELECT 2", "params": []})]

    @pytest.mark.asyncio
    async def test_update_always_touches_updated_at_and_casts_parameters(self):
        aid = uuid4()
        db = make_db([{"id": aid}])
        repo = AnalysisRepository(db)

        assert await repo.update(aid, {"name": "n", "parameters": self.PARAMS}) is True
        query, values, _ = q(db)
        assert "SET name = $2, parameters = $3::jsonb, updated_at = NOW() WHERE id = $1" in query
        assert values == [aid, "n", json.dumps(self.PARAMS)]
        await repo.update(aid, {})  # sem campos: só o updated_at (invalida o cache)
        assert "SET updated_at = NOW() WHERE id = $1" in q(db)[0]
        db.execute_query.return_value = []
        assert await repo.update(aid, {"name": "x"}) is False

    @pytest.mark.asyncio
    async def test_touch_history_delete_and_profiles(self):
        aid, pid = uuid4(), uuid4()
        db = make_db(datetime(2026, 2, 2))
        repo = AnalysisRepository(db)

        assert await repo.touch(aid) == datetime(2026, 2, 2)
        assert "RETURNING updated_at" in q(db)[0] and q(db)[2] == {"scalar": True}
        db.execute_query.return_value = 1
        assert await repo.has_history(aid) is True
        db.execute_query.return_value = None
        assert await repo.has_history(aid) is False
        db.execute_query.return_value = [{"id": aid}]
        assert await repo.delete(aid) is True
        db.execute_query.return_value = [{"id": pid}]
        await repo.get_profiles(aid)
        assert "JOIN profile_analyses pa" in q(db)[0] and q(db)[1] == [aid]

        tx = make_db()
        await repo.replace_profiles(aid, [pid], tx)
        assert ex(tx, 0) == ("DELETE FROM profile_analyses WHERE analysis_id = $1", [aid])
        assert ex(tx, 1)[1] == [aid, [pid]]
        empty = make_db()
        await repo.replace_profiles(aid, [], empty)
        assert empty.execute.await_count == 1


class TestDataSourceRepository:
    CONFIG = {"host": "h", "password": "cifrada"}

    @pytest.mark.asyncio
    async def test_get_by_id_decodes_json_string_config(self):
        row = dict(id=uuid4(), name="ds", type="postgresql", connection_config=json.dumps(self.CONFIG), is_active=True)
        db = make_db([row])
        repo = DataSourceRepository(db)

        ds = await repo.get_by_id(row["id"])
        assert ds.connection_config == self.CONFIG and ds.type == "postgresql"
        db.execute_query.return_value = [{**row, "connection_config": self.CONFIG}]  # já dict
        assert (await repo.get_by_id(row["id"])).connection_config == self.CONFIG
        db.execute_query.return_value = []
        assert await repo.get_by_id(uuid4()) is None

    @pytest.mark.asyncio
    async def test_list_page_never_selects_connection_config(self):
        db = make_db()
        db.execute_query.side_effect = [2, [{"id": 1}]]

        rows, total = await DataSourceRepository(db).list_page("vend", "mysql", True, 10, 0)

        query, values, _ = q(db)
        assert "connection_config" not in query and "analyses_count" in query
        assert "ORDER BY ds.name, ds.id LIMIT $4 OFFSET $5" in query
        assert values == ["%vend%", "mysql", True, 10, 0] and (rows, total) == ([{"id": 1}], 2)

    @pytest.mark.asyncio
    async def test_summary_and_analyses(self):
        dsid = uuid4()
        db = make_db([{"id": dsid}])
        repo = DataSourceRepository(db)

        assert await repo.get_summary(dsid) == {"id": dsid}
        db.execute_query.return_value = []
        assert await repo.get_summary(dsid) is None
        await repo.get_analyses(dsid)
        assert "FROM analyses WHERE data_source_id = $1" in q(db)[0] and q(db)[1] == [dsid]

    @pytest.mark.asyncio
    async def test_create_serializes_config_as_jsonb(self):
        new_id = uuid4()
        db = make_db(new_id)

        assert await DataSourceRepository(db).create("ds", "oracle", self.CONFIG, True, "admin") == new_id

        query, values, kwargs = q(db)
        assert "$3::jsonb" in query and kwargs == {"scalar": True}
        assert values == ["ds", "oracle", json.dumps(self.CONFIG), True, "admin"]

    @pytest.mark.asyncio
    async def test_update_serializes_only_connection_config_and_touches_updated_at(self):
        dsid = uuid4()
        db = make_db([{"id": dsid}])
        repo = DataSourceRepository(db)

        assert await repo.update(dsid, {"name": "n", "connection_config": self.CONFIG, "is_active": False}) is True
        query, values, _ = q(db)
        assert "SET name = $2, connection_config = $3::jsonb, is_active = $4, updated_at = NOW()" in query
        assert values == [dsid, "n", json.dumps(self.CONFIG), False]
        db.execute_query.return_value = []
        assert await repo.update(dsid, {"name": "x"}) is False

    @pytest.mark.asyncio
    async def test_delete_and_touch_analyses(self):
        dsid = uuid4()
        db = make_db([{"id": dsid}])
        repo = DataSourceRepository(db)

        assert await repo.delete(dsid) is True
        db.execute_query.return_value = []
        assert await repo.delete(dsid) is False
        await repo.touch_analyses(dsid)
        query, values, _ = q(db)
        assert "UPDATE analyses SET updated_at = NOW() WHERE data_source_id = $1" in query and values == [dsid]
