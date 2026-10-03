"""security/password_hash.py — F12_AUTENTICACAO_PERFIS.md §6.1."""

import bcrypt

from security.password_hash import verify_password

_HASH = bcrypt.hashpw(b"s3nha", bcrypt.gensalt(rounds=4)).decode()


class TestPasswordHash:
    def test_verify_password_correct(self):
        assert verify_password("s3nha", _HASH) is True

    def test_verify_password_wrong(self):
        assert verify_password("outra", _HASH) is False

    def test_verify_password_none_hash_returns_false(self):
        assert verify_password("s3nha", None) is False
        assert verify_password("s3nha", "") is False

    def test_verify_password_malformed_hash_returns_false(self):
        assert verify_password("s3nha", "isto-nao-e-bcrypt") is False

    def test_verify_password_over_72_bytes_returns_false(self):
        long_password = "a" * 73
        long_hash = bcrypt.hashpw(b"a" * 72, bcrypt.gensalt(rounds=4)).decode()

        assert verify_password(long_password, long_hash) is False

    def test_verify_password_counts_bytes_not_characters(self):
        assert verify_password("é" * 37, _HASH) is False  # 74 bytes em UTF-8
