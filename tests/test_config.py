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


class TestQueryRetrySettings:
    """F14 §7 — QUERY_RETRY_MAX_ATTEMPTS / QUERY_RETRY_BACKOFF_BASE_MS."""

    def test_defaults(self):
        s = Settings()
        assert s.query_retry_max_attempts == 3
        assert s.query_retry_backoff_base_ms == 200

    def test_attempts_below_one_raises(self):
        with pytest.raises(ValueError, match="QUERY_RETRY_MAX_ATTEMPTS"):
            Settings(query_retry_max_attempts=0)

    def test_one_attempt_means_no_retry_and_is_valid(self):
        assert Settings(query_retry_max_attempts=1).query_retry_max_attempts == 1

    def test_negative_backoff_raises(self):
        with pytest.raises(ValueError, match="QUERY_RETRY_BACKOFF_BASE_MS"):
            Settings(query_retry_backoff_base_ms=-1)

    def test_zero_backoff_is_valid(self):
        assert Settings(query_retry_backoff_base_ms=0).query_retry_backoff_base_ms == 0


class TestPoolSettings:
    """F15 §6.1 — PG_POOL_* / CONFIG_DB_POOL_*."""

    def test_defaults(self):
        s = Settings()
        assert (s.pg_pool_min_size, s.pg_pool_max_size) == (10, 10)
        assert (s.config_db_pool_min_size, s.config_db_pool_max_size) == (10, 10)

    @pytest.mark.parametrize(
        "prefix,min_field,max_field",
        [
            ("PG_POOL", "pg_pool_min_size", "pg_pool_max_size"),
            ("CONFIG_DB_POOL", "config_db_pool_min_size", "config_db_pool_max_size"),
        ],
    )
    def test_max_menor_que_min_falha(self, prefix, min_field, max_field):
        with pytest.raises(ValueError, match=f"{prefix}_MAX_SIZE"):
            Settings(**{min_field: 5, max_field: 4})

    @pytest.mark.parametrize(
        "prefix,min_field",
        [("PG_POOL", "pg_pool_min_size"), ("CONFIG_DB_POOL", "config_db_pool_min_size")],
    )
    def test_min_menor_que_1_falha(self, prefix, min_field):
        with pytest.raises(ValueError, match=f"{prefix}_MIN_SIZE"):
            Settings(**{min_field: 0})

    def test_pool_menor_e_valido(self):
        s = Settings(pg_pool_min_size=2, pg_pool_max_size=5)
        assert (s.pg_pool_min_size, s.pg_pool_max_size) == (2, 5)


class TestTlsEnabledSetting:
    """TLS_ENABLED — HTTP puro só em desenvolvimento local (run_https.py)."""

    def test_enabled_by_default(self):
        assert Settings.model_fields["tls_enabled"].default is True

    def test_can_be_disabled(self):
        assert Settings(tls_enabled=False).tls_enabled is False
