"""Token de acesso opaco — F12_AUTENTICACAO_PERFIS.md §4.4 (ADR-007).

O token bruto só existe na resposta de POST /auth/token; no banco fica apenas
o hash SHA-256 (access_tokens.token_hash).
"""

import hashlib
import secrets


def generate_token() -> str:
    """Token opaco URL-safe com 256 bits de entropia (43 caracteres)."""
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """SHA-256 hexadecimal (64 caracteres) do token bruto."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
