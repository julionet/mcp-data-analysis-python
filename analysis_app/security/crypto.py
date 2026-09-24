"""Cifra/decifra de credenciais em repouso via Fernet — ARQUITETURA.md §8.2,
F4_EXECUTION_ENGINE.md §4.4."""

from cryptography.fernet import Fernet

from config import settings


def _fernet() -> Fernet:
    return Fernet(settings.fernet_key.encode())


def decrypt_password(encrypted: str) -> str:
    """Descriptografa connection_config.password usando Fernet
    (FERNET_KEY do .env). Ver ARQUITETURA.md §8.2."""
    return _fernet().decrypt(encrypted.encode()).decode()


def encrypt_password(plain: str) -> str:
    """Usado por scripts de cadastro manual (ex.: seed_analise_vendas.py)."""
    return _fernet().encrypt(plain.encode()).decode()
