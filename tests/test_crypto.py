"""Testes unitários da F4 — ver F4_EXECUTION_ENGINE.md §6.1 (TestCryptoUtils)."""

from security.crypto import decrypt_password, encrypt_password


class TestCryptoUtils:
    def test_decrypt_password_roundtrip(self):
        plain = "Senha123"

        encrypted = encrypt_password(plain)
        decrypted = decrypt_password(encrypted)

        assert decrypted == plain
        assert encrypted != plain
