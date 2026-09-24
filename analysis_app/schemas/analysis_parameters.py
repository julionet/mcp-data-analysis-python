"""Schema de analyses.parameters e conversões — ARQUITETURA.md §2.3, F4_EXECUTION_ENGINE.md §4.4.

Fonte única de verdade usada tanto pelo Execution Engine (F4, to_pydantic_model)
quanto pelo list_tools do MCP (F5, to_json_schema).
"""

from datetime import date, datetime
from typing import Literal, Optional, Type

from pydantic import BaseModel, Field, create_model

from schemas.exceptions import InvalidAnalysisSchemaError

_PYTHON_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "date": date,
    "datetime": datetime,
}

_JSON_SCHEMA_TYPES: dict[str, tuple[str, str | None]] = {
    "string": ("string", None),
    "integer": ("integer", None),
    "number": ("number", None),
    "boolean": ("boolean", None),
    "date": ("string", "date"),
    "datetime": ("string", "date-time"),
}

_NUMERIC_TYPES = {"integer", "number"}
_ENUM_COMPATIBLE_TYPES = {"string", "integer", "number"}


def validate_schema(parameters: dict) -> None:
    """Valida a ESTRUTURA do JSON de analyses.parameters (§2.3) — não os
    valores enviados pelo cliente. Levanta InvalidAnalysisSchemaError se:
    - 'type' fora de {string, integer, number, boolean, date, datetime}
    - 'required' não é bool
    - 'enum' presente mas incompatível com o 'type'
    - 'min'/'max' presentes fora de number/integer
    Chamada ANTES de to_pydantic_model(), pois cadastro de análises em V1.0
    é 100% manual via INSERT — sem UI de validação no cadastro."""
    for name, definition in (parameters or {}).items():
        param_type = definition.get("type")
        if param_type not in _PYTHON_TYPES:
            raise InvalidAnalysisSchemaError(
                f"Parâmetro '{name}': type '{param_type}' inválido — "
                f"deve ser um de {sorted(_PYTHON_TYPES)}"
            )

        required = definition.get("required", False)
        if not isinstance(required, bool):
            raise InvalidAnalysisSchemaError(
                f"Parâmetro '{name}': 'required' deve ser bool, recebeu {required!r}"
            )

        if definition.get("enum") is not None and param_type not in _ENUM_COMPATIBLE_TYPES:
            raise InvalidAnalysisSchemaError(
                f"Parâmetro '{name}': 'enum' incompatível com type '{param_type}'"
            )

        if param_type not in _NUMERIC_TYPES and (
            definition.get("min") is not None or definition.get("max") is not None
        ):
            raise InvalidAnalysisSchemaError(
                f"Parâmetro '{name}': 'min'/'max' só são válidos para number/integer, "
                f"não para '{param_type}'"
            )


def to_pydantic_model(parameters: dict) -> Type[BaseModel]:
    """Gera dinamicamente um modelo Pydantic a partir de analyses.parameters,
    para validar os VALORES recebidos do cliente. Assume que validate_schema()
    já rodou (não revalida a estrutura do schema)."""
    fields: dict[str, tuple] = {}

    for name, definition in (parameters or {}).items():
        python_type: type = _PYTHON_TYPES[definition["type"]]

        enum = definition.get("enum")
        if enum is not None:
            python_type = Literal[tuple(enum)]

        field_kwargs: dict = {}
        if definition.get("description"):
            field_kwargs["description"] = definition["description"]
        if definition.get("min") is not None:
            field_kwargs["ge"] = definition["min"]
        if definition.get("max") is not None:
            field_kwargs["le"] = definition["max"]

        if definition.get("required", False):
            fields[name] = (python_type, Field(..., **field_kwargs))
        else:
            default = definition.get("default")
            fields[name] = (Optional[python_type], Field(default, **field_kwargs))

    return create_model("AnalysisParamsModel", **fields)


def to_json_schema(parameters: dict) -> dict:
    """Converte analyses.parameters para JSON Schema padrão MCP.
    Implementado nesta feature; consumido pelo F5 (list_tools)."""
    properties: dict[str, dict] = {}
    required: list[str] = []

    for name, definition in (parameters or {}).items():
        json_type, json_format = _JSON_SCHEMA_TYPES[definition["type"]]
        prop: dict = {"type": json_type}
        if json_format:
            prop["format"] = json_format
        if definition.get("description"):
            prop["description"] = definition["description"]
        if definition.get("enum") is not None:
            prop["enum"] = definition["enum"]
        if definition.get("min") is not None:
            prop["minimum"] = definition["min"]
        if definition.get("max") is not None:
            prop["maximum"] = definition["max"]
        if definition.get("default") is not None:
            prop["default"] = definition["default"]

        properties[name] = prop
        if definition.get("required", False):
            required.append(name)

    return {"type": "object", "properties": properties, "required": required}
