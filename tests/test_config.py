"""Testes de validação de Settings — F7_CACHE_SERVICE.md §7 (CACHE_BACKEND)."""

import pytest

from config import Settings


class TestCacheBackendValidation:
    def test_memory_is_valid(self):
        assert Settings(cache_backend="memory").cache_backend == "memory"

    def test_none_is_valid(self):
        """CACHE_BACKEND=none — kill-switch global de cache (ajuste retroativo, 2026-09-27)."""
        assert Settings(cache_backend="none").cache_backend == "none"

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError, match="CACHE_BACKEND"):
            Settings(cache_backend="redis")


class TestAccessTokenExpirationSettings:
    """F12 §6.3 — ACCESS_TOKEN_EXPIRATION_DAYS / ACCESS_TOKEN_MAX_EXPIRATION_DAYS."""

    def test_defaults(self):
        s = Settings()
        assert s.access_token_expiration_days == 90
        assert s.access_token_max_expiration_days == 365

    @pytest.mark.parametrize("field", ["access_token_expiration_days", "access_token_max_expiration_days"])
    def test_below_one_raises(self, field):
        with pytest.raises(ValueError, match="ACCESS_TOKEN"):
            Settings(**{field: 0})

    def test_expiration_above_max_raises(self):
        with pytest.raises(ValueError, match="ACCESS_TOKEN"):
            Settings(access_token_expiration_days=100, access_token_max_expiration_days=30)


class TestTlsEnabledSetting:
    """TLS_ENABLED — HTTP puro só em desenvolvimento local (run_https.py)."""

    def test_enabled_by_default(self):
        assert Settings.model_fields["tls_enabled"].default is True

    def test_can_be_disabled(self):
        assert Settings(tls_enabled=False).tls_enabled is False
