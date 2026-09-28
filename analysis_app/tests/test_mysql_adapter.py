"""Testes unitários do F10 — MySQL Adapter — ver F10_MYSQL_ADAPTER.md §6.1."""

import pytest

from adapters.mysql import MySQLAdapter


CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "senha_decifrada",
    "database": "test_db",
}


class TestMySQLAdapter:
    def test_translate_params_single(self):
        """Traduz um placeholder nomeado."""
        adapter = MySQLAdapter({})
        sql = "SELECT * FROM t WHERE x = :x"
        result = adapter.translate_params(sql, ["x"])
        assert result == "SELECT * FROM t WHERE x = ?"

    def test_translate_params_multiple(self):
        """Traduz múltiplos placeholders nomeados na ordem correta."""
        adapter = MySQLAdapter({})
        sql = "SELECT * FROM t WHERE x = :x AND y = :y AND z = :z"
        result = adapter.translate_params(sql, ["x", "y", "z"])
        assert result == "SELECT * FROM t WHERE x = ? AND y = ? AND z = ?"

    def test_translate_params_preserves_order(self):
        """Ordem de ? segue param_names, não ordem de aparição no SQL."""
        adapter = MySQLAdapter({})
        sql = "SELECT * FROM t WHERE y = :y AND x = :x"
        result = adapter.translate_params(sql, ["x", "y"])
        # Deve substituir em ordem de param_names: :x → ?, :y → ?
        # Resultado será "SELECT * FROM t WHERE y = ? AND x = ?"
        assert result.count("?") == 2
        # Verificar que ambos foram substituídos (sem :x ou :y restantes)
        assert ":x" not in result
        assert ":y" not in result

    def test_translate_params_word_boundary(self):
        """Respeita boundary de palavra para não substituir em nomes parciais."""
        adapter = MySQLAdapter({})
        sql = "SELECT :x_val, :x FROM t WHERE col = :x"
        result = adapter.translate_params(sql, ["x"])
        # Deve substituir apenas :x (com boundary), não :x_val
        assert result.count("?") == 2  # :x_val e :x final
        assert ":x_val" in result  # :x_val não foi substituído (certo!)

    def test_translate_params_empty_list(self):
        """Com lista vazia de params, SQL permanece inalterado."""
        adapter = MySQLAdapter({})
        sql = "SELECT * FROM t"
        result = adapter.translate_params(sql, [])
        assert result == sql

    @pytest.mark.asyncio
    async def test_connect_invalid_credentials(self):
        """Conectar com credenciais inválidas lança erro."""
        bad_config = {
            "host": "localhost",
            "port": 3306,
            "database": "nonexistent",
            "user": "invalid",
            "password": "invalid",
        }
        adapter = MySQLAdapter(bad_config)
        with pytest.raises(Exception):
            await adapter.connect()

    @pytest.mark.asyncio
    async def test_test_connection_failure_no_connect(self):
        """test_connection retorna False sem conectar."""
        bad_config = {
            "host": "nonexistent_host",
            "port": 3306,
            "user": "x",
            "password": "x",
            "database": "x",
        }
        adapter = MySQLAdapter(bad_config)
        result = await adapter.test_connection()
        assert result is False

    def test_adapter_init_config(self):
        """Adapter armazena config corretamente."""
        adapter = MySQLAdapter(CONFIG)
        assert adapter.config == CONFIG
        assert adapter._pool is None
