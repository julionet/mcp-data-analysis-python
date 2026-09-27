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
