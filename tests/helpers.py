"""Helpers compartilhados pelos testes."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from adapters.postgresql import PostgreSQLAdapter
from schemas.auth import AuthenticatedUser


def make_fake_adapter() -> AsyncMock:
    """AsyncMock de DatabaseAdapter com translate_params síncrono e real (PostgreSQL).

    `translate_params` é um método síncrono no adapter; num AsyncMock puro ele
    viraria corrotina e o SQL "traduzido" seria um objeto coroutine.
    """
    adapter = AsyncMock()
    adapter.translate_params = MagicMock(side_effect=PostgreSQLAdapter({}).translate_params)
    return adapter


def make_user(name: str = "Maria") -> AuthenticatedUser:
    """AuthenticatedUser de teste (F12), com UUID novo a cada chamada."""
    return AuthenticatedUser(id=uuid4(), name=name)
