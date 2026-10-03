"""security/token_auth.py — F12_AUTENTICACAO_PERFIS.md §6.1."""

import hashlib
import re

from security.token_auth import generate_token, hash_token


class TestTokenAuth:
    def test_generate_token_is_url_safe_and_unique(self):
        tokens = {generate_token() for _ in range(50)}

        assert len(tokens) == 50
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", t) for t in tokens)

    def test_hash_token_is_deterministic_sha256(self):
        assert hash_token("abc") == hash_token("abc")
        assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
        assert len(hash_token("abc")) == 64
        assert hash_token("abc") != hash_token("abd")
