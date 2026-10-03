"""validate_select_only — o engine só executa consultas SELECT."""

import pytest

from schemas.exceptions import InvalidAnalysisSchemaError
from schemas.sql_validation import validate_select_only


class TestValidateSelectOnly:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1",
            "  select * from vendas where data BETWEEN :data_inicial AND :data_final",
            "-- comentário\nSELECT a FROM t",
            "/* bloco */ SELECT a FROM t",
            "SELECT a FROM t ORDER BY a",
            "SELECT REPLACE(nome, 'a', 'b') FROM t",
            "SELECT 'delete from t' AS txt FROM t",
            'SELECT "update" FROM t',
            "SELECT `delete` FROM t",
            "SELECT created_at, updated_by FROM t",
            "SELECT :produto::text IS NULL OR d ILIKE '%' || :produto || '%' FROM t",
            "SELECT a FROM t WHERE x = :update",  # nome de parâmetro não conta como palavra
        ],
    )
    def test_accepts_select(self, sql):
        validate_select_only(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "",
            "   ",
            "INSERT INTO t (a) VALUES (1)",
            "UPDATE t SET a = 1",
            "DELETE FROM t",
            "DROP TABLE t",
            "TRUNCATE t",
            "WITH x AS (SELECT 1) SELECT * FROM x",  # CTE fora do subconjunto comum (F11/F9 §8.4)
            "CALL proc()",
            "EXEC proc",
            "SELECT * INTO nova FROM t",
            "SELECT a FROM t FOR UPDATE",
            "SELECT 1; DROP TABLE t",
            "SELECT 1;",
            "-- SELECT\nDELETE FROM t",
            "/* SELECT */ UPDATE t SET a = 1",
        ],
    )
    def test_rejects_non_select(self, sql):
        with pytest.raises(InvalidAnalysisSchemaError):
            validate_select_only(sql)

    def test_message_names_forbidden_keyword(self):
        with pytest.raises(InvalidAnalysisSchemaError, match="INTO"):
            validate_select_only("SELECT * INTO nova FROM t")
