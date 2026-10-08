"""database/connection.py — F17 A5: fail-fast do Config DB sem vazar a senha no log."""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from config import settings
from database import connection


class TestConnectConfigDb:
    @pytest.mark.asyncio
    async def test_connection_failure_is_logged_without_password_and_reraised(self, caplog):
        boom = OSError("connection refused")

        with (
            patch.object(settings, "postgres_config_password", "S3gr3d0-Unico-9f2"),
            patch.object(connection.config_db_adapter, "connect", AsyncMock(side_effect=boom)),
            caplog.at_level(logging.ERROR, logger="database.connection"),
            pytest.raises(OSError) as raised,
        ):
            await connection.connect_config_db()

        assert raised.value is boom  # fail-fast: o startup não engole o erro
        text = " ".join(r.getMessage() for r in caplog.records)
        assert settings.postgres_config_host in text and str(settings.postgres_config_port) in text
        assert settings.postgres_config_database in text and settings.postgres_config_user in text
        assert "S3gr3d0-Unico-9f2" not in text

    @pytest.mark.asyncio
    async def test_successful_connection_does_not_log_an_error(self, caplog):
        with (
            patch.object(connection.config_db_adapter, "connect", AsyncMock()) as connect,
            caplog.at_level(logging.ERROR, logger="database.connection"),
        ):
            await connection.connect_config_db()

        connect.assert_awaited_once()
        assert caplog.records == []

    @pytest.mark.asyncio
    async def test_disconnect_and_health_check_delegate_to_the_adapter(self):
        with (
            patch.object(connection.config_db_adapter, "disconnect", AsyncMock()) as disconnect,
            patch.object(connection.config_db_adapter, "test_connection", AsyncMock(return_value=False)),
        ):
            await connection.disconnect_config_db()
            assert await connection.check_postgres() is False

        disconnect.assert_awaited_once()
