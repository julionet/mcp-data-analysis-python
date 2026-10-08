"""Senha com bcrypt — F12_AUTENTICACAO_PERFIS.md §4.4 e F23 §4.3/§4.4.1.

verify_password() é síncrona e CPU-bound (~100 ms) — chame via asyncio.to_thread()
para não bloquear o event loop. hash_password() já faz isso. A política de senha
(F23) vale só para gravação; a verificação aceita qualquer senha já gravada.
"""

import asyncio

import bcrypt

_BCRYPT_MAX_BYTES = 72
_BCRYPT_ROUNDS = 12
_MIN_LENGTH = 6


class PasswordPolicyError(Exception):
    """Senha fora da política; `reason` é a regra violada, em português."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_password_policy(password: str) -> None:
    """Mínimo 6 caracteres; ≥ 1 maiúscula, minúscula, número e símbolo; máximo 72 bytes.
    Espaço não conta como símbolo; letras acentuadas contam como letra (F23 decisão 17)."""
    if len(password.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        raise PasswordPolicyError(f"A senha deve ter no máximo {_BCRYPT_MAX_BYTES} bytes.")
    if len(password) < _MIN_LENGTH:
        raise PasswordPolicyError(f"A senha deve ter no mínimo {_MIN_LENGTH} caracteres.")
    if not any(c.isupper() for c in password):
        raise PasswordPolicyError("A senha deve ter ao menos uma letra maiúscula.")
    if not any(c.islower() for c in password):
        raise PasswordPolicyError("A senha deve ter ao menos uma letra minúscula.")
    if not any(c.isdigit() for c in password):
        raise PasswordPolicyError("A senha deve ter ao menos um número.")
    if not any(not c.isalnum() and not c.isspace() for c in password):
        raise PasswordPolicyError("A senha deve ter ao menos um caractere especial (símbolo).")


async def hash_password(password: str) -> str:
    """bcrypt custo 12, em thread. Recusa senha > 72 bytes (o bcrypt a truncaria)."""
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > _BCRYPT_MAX_BYTES:
        raise PasswordPolicyError(f"A senha deve ter no máximo {_BCRYPT_MAX_BYTES} bytes.")
    hashed = await asyncio.to_thread(
        bcrypt.hashpw, password_bytes, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    )
    return hashed.decode("utf-8")


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
