"""Testes unitários da F4 — ver F4_EXECUTION_ENGINE.md §6.1 (TestAnalysisParametersSchema)."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from schemas.analysis_parameters import to_json_schema, to_pydantic_model, validate_schema
from schemas.exceptions import InvalidAnalysisSchemaError

VALID_PARAMETERS = {
    "data_inicial": {
        "type": "date",
        "required": True,
        "description": "Data inicial do periodo de vendas (YYYY-MM-DD)",
    },
    "data_final": {
        "type": "date",
        "required": True,
        "description": "Data final do periodo de vendas (YYYY-MM-DD)",
    },
    "pago": {
        "type": "boolean",
        "required": False,
        "description": "Filtrar por status de pagamento",
    },
}


class TestAnalysisParametersSchema:
    def test_validate_schema_rejects_invalid_type(self):
        with pytest.raises(InvalidAnalysisSchemaError):
            validate_schema({"regiao": {"type": "foo", "required": False}})

    def test_validate_schema_accepts_valid_schema(self):
        validate_schema(VALID_PARAMETERS)  # não deve levantar

    def test_validate_schema_rejects_non_bool_required(self):
        with pytest.raises(InvalidAnalysisSchemaError):
            validate_schema({"regiao": {"type": "string", "required": "sim"}})

    def test_validate_schema_rejects_enum_incompatible_with_type(self):
        with pytest.raises(InvalidAnalysisSchemaError):
            validate_schema(
                {"pago": {"type": "boolean", "required": False, "enum": [True, False]}}
            )

    def test_validate_schema_rejects_min_max_outside_numeric(self):
        with pytest.raises(InvalidAnalysisSchemaError):
            validate_schema(
                {"nome": {"type": "string", "required": False, "min": 1, "max": 10}}
            )

    def test_validate_schema_accepts_min_max_on_numeric(self):
        validate_schema(
            {"quantidade": {"type": "integer", "required": False, "min": 1, "max": 10}}
        )

    def test_to_pydantic_model_builds_correct_types(self):
        model_cls = to_pydantic_model(
            {
                "nome": {"type": "string", "required": True},
                "quantidade": {"type": "integer", "required": True},
                "preco": {"type": "number", "required": True},
                "pago": {"type": "boolean", "required": True},
                "data": {"type": "date", "required": True},
                "criado_em": {"type": "datetime", "required": True},
            }
        )
        instance = model_cls(
            nome="produto",
            quantidade=3,
            preco=9.9,
            pago=True,
            data="2026-01-01",
            criado_em="2026-01-01T10:00:00",
        )

        assert isinstance(instance.nome, str)
        assert isinstance(instance.quantidade, int)
        assert isinstance(instance.preco, float)
        assert isinstance(instance.pago, bool)
        assert isinstance(instance.data, date)
        assert isinstance(instance.criado_em, datetime)

    def test_to_pydantic_model_enforces_required_fields(self):
        model_cls = to_pydantic_model(VALID_PARAMETERS)

        with pytest.raises(ValidationError):
            model_cls(data_final="2026-01-31")  # falta data_inicial (required)

    def test_to_pydantic_model_optional_field_defaults_to_none(self):
        model_cls = to_pydantic_model(VALID_PARAMETERS)

        instance = model_cls(data_inicial="2026-01-01", data_final="2026-01-31")

        assert instance.pago is None

    def test_to_pydantic_model_enforces_enum(self):
        model_cls = to_pydantic_model(
            {
                "regiao": {
                    "type": "string",
                    "required": True,
                    "enum": ["Norte", "Sul"],
                }
            }
        )

        with pytest.raises(ValidationError):
            model_cls(regiao="Leste")

    def test_to_json_schema_matches_mcp_input_schema_format(self):
        result = to_json_schema(VALID_PARAMETERS)

        assert result["type"] == "object"
        assert result["required"] == ["data_inicial", "data_final"]
        assert result["properties"]["data_inicial"] == {
            "type": "string",
            "format": "date",
            "description": "Data inicial do periodo de vendas (YYYY-MM-DD)",
        }
        assert result["properties"]["pago"]["type"] == "boolean"
        assert "pago" not in result["required"]
