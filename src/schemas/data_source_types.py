"""Tipos de data source suportados e validação do `connection_config` — F24 §4.4.1.

Espelha DATABASE_SCHEMA.md §4 e o `AdapterFactory`; um teste garante que os tipos coincidem.
"""

from dataclasses import dataclass, field
from typing import Any

from config import settings
from schemas.admin import InvalidConnectionConfigError, UnsupportedDataSourceTypeError

SSLMODES = ("prefer", "verify-full")


@dataclass(frozen=True)
class DataSourceType:
    type: str
    required: tuple[str, ...]
    optional: dict[str, Any] = field(default_factory=dict)  # nome -> padrão (None = padrão do .env/adapter)
    one_of: tuple[tuple[str, ...], ...] = ()  # grupos em que exatamente um é obrigatório

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(self.required) | frozenset(self.optional) | {k for g in self.one_of for k in g}


_COMMON = ("host", "database", "user", "password")

DATA_SOURCE_TYPES: dict[str, DataSourceType] = {
    t.type: t
    for t in (
        DataSourceType(
            "postgresql",
            ("host", "port", "database", "user", "password"),
            {"pool_min_size": None, "pool_max_size": None},
        ),
        DataSourceType("mysql", _COMMON, {"port": 3306}),
        DataSourceType(
            "sqlserver",
            _COMMON,
            {"port": 1433, "driver": "ODBC Driver 18 for SQL Server", "sslmode": "prefer"},
        ),
        DataSourceType(
            "oracle", ("host", "user", "password"), {"port": 1521}, one_of=(("service_name", "sid"),)
        ),
    )
}

_STRING_KEYS = {"host", "database", "user", "password", "driver", "service_name", "sid"}


def get_type(type_: str) -> DataSourceType:
    spec = DATA_SOURCE_TYPES.get(type_)
    if spec is None:
        raise UnsupportedDataSourceTypeError(type_, sorted(DATA_SOURCE_TYPES))
    return spec


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_connection_config(type_: str, config: dict[str, Any]) -> None:
    """Levanta UnsupportedDataSourceTypeError / InvalidConnectionConfigError (lista todos os problemas)."""
    spec = get_type(type_)
    problems: list[str] = []

    unknown = sorted(set(config) - spec.allowed)
    if unknown:
        problems.append(f"chave(s) desconhecida(s) para '{type_}': {', '.join(unknown)}")
    for key in spec.required:
        if config.get(key) in (None, ""):
            problems.append(f"'{key}' é obrigatório")
    for group in spec.one_of:
        present = [k for k in group if config.get(k) not in (None, "")]
        if len(present) != 1:
            problems.append(f"informe exatamente um entre {' ou '.join(group)}")

    for key, value in config.items():
        if key in unknown or value is None:
            continue
        if key in _STRING_KEYS and not (isinstance(value, str) and value.strip()):
            problems.append(f"'{key}' deve ser um texto não vazio")
        elif key == "port" and not (_is_int(value) and 1 <= value <= 65535):
            problems.append("'port' deve ser um inteiro entre 1 e 65535")
        elif key in ("pool_min_size", "pool_max_size") and not (_is_int(value) and value >= 1):
            problems.append(f"'{key}' deve ser um inteiro maior ou igual a 1")
        elif key == "sslmode" and value not in SSLMODES:
            problems.append(f"'sslmode' deve ser um de {', '.join(SSLMODES)}")

    if type_ == "postgresql":
        # O adapter usa o padrão do .env para o que faltar: o par efetivo é que precisa ser coerente
        # (senão o asyncpg recusa o pool só na primeira execução).
        lo = config.get("pool_min_size", settings.pg_pool_min_size)
        hi = config.get("pool_max_size", settings.pg_pool_max_size)
        if _is_int(lo) and _is_int(hi) and lo > hi:
            problems.append(
                f"pool_min_size efetivo ({lo}) não pode ser maior que pool_max_size efetivo ({hi}); "
                "o que não for informado assume PG_POOL_MIN_SIZE/PG_POOL_MAX_SIZE do .env"
            )

    if problems:
        raise InvalidConnectionConfigError("connection_config inválido: " + "; ".join(problems) + ".")
