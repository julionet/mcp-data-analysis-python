"""Testes unitários da F14 — contrato de error_code/retryable (spec §4.2)."""

import pytest

from schemas.exceptions import (
    AnalysisNotFoundError,
    DataSourceConnectionError,
    InvalidAnalysisSchemaError,
    InvalidCacheFrequencyError,
    InvalidParametersError,
    QueryExecutionError,
    QueryTimeoutError,
    error_info,
)


@pytest.mark.parametrize(
    ("exc", "code", "retryable"),
    [
        (AnalysisNotFoundError("x"), "ANALYSIS_NOT_FOUND", False),
        (InvalidParametersError("x"), "INVALID_PARAMETERS", False),
        (InvalidAnalysisSchemaError("x"), "INVALID_ANALYSIS_CONFIG", False),
        (InvalidCacheFrequencyError("x"), "INVALID_ANALYSIS_CONFIG", False),
        (DataSourceConnectionError("x"), "DATA_SOURCE_UNAVAILABLE", True),
        (QueryTimeoutError("x"), "QUERY_TIMEOUT", True),
        (QueryExecutionError("x"), "QUERY_FAILED", False),
    ],
)
def test_error_info_per_exception(exc, code, retryable):
    assert error_info(exc) == (code, retryable)


@pytest.mark.parametrize("exc", [ValueError("x"), RuntimeError("x"), Exception()])
def test_error_info_unknown_exception_is_internal_error(exc):
    assert error_info(exc) == ("INTERNAL_ERROR", False)


def test_query_errors_are_still_data_source_connection_errors():
    # Os `except DataSourceConnectionError` de AnalysisService devem continuar pegando as subclasses.
    assert issubclass(QueryTimeoutError, DataSourceConnectionError)
    assert issubclass(QueryExecutionError, DataSourceConnectionError)
