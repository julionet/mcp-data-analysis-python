"""Verificação de senha com bcrypt — F12_AUTENTICACAO_PERFIS.md §4.4.

Só verifica: o hash é gerado fora do código (§8.2, INSERT manual do admin).
bcrypt é CPU-bound (~100 ms) — chame verify_password() via asyncio.to_thread()
para não bloquear o event loop.
"""

import bcrypt

_BCRYPT_MAX_BYTES = 72


def verify_password(password: str, password_hash: str | None) -> bool:
    """bcrypt.checkpw. Devolve False — nunca lança — se `password_hash` for
    None/inválido ou se a senha passar de 72 bytes (limite do bcrypt)."""
    if not password_hash:
        return False
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
    except ValueError:  # hash malformado
        return False
