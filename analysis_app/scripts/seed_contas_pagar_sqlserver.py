#!/usr/bin/env python3
"""
Gera os INSERTs SQL para cadastrar o data_source SQL Server "SedareDB" e a
análise "contas_a_pagar_por_fornecedor" (F11), cifrando a senha com Fernet
(FERNET_KEY do .env, via security.crypto.encrypt_password).

Uso:
    cd analysis_app
    python scripts/seed_contas_pagar_sqlserver.py --password 'senh@123' > seed_contas_pagar.sql
    # ou, sem expor a senha no histórico do shell:
    python scripts/seed_contas_pagar_sqlserver.py > seed_contas_pagar.sql   # pede a senha

Os INSERTs são para o banco de CONFIG (analysis_config), NÃO para o SedareDB.
A senha em texto puro nunca é gravada no arquivo gerado — só a versão cifrada.

O SQL do step usa placeholders agnósticos ":nome" (não "@nome"): o
SQLServerAdapter traduz ":nome" → "@nome" → "?" na execução (F11 §4.2).
Os nomes em "params" precisam bater EXATAMENTE (maiúsculas/minúsculas) com os
usados no SQL.
"""
import argparse
import getpass
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from security.crypto import encrypt_password  # noqa: E402

# --- Valores ajustáveis ---
DATA_SOURCE_NAME = "sedare_sqlserver"
ANALYSIS_NAME = "contas_a_pagar_por_fornecedor"
ANALYSIS_DESCRIPTION = (
    "Retorna títulos a pagar (fornecedor, vencimento, valor receita, valor despesa, "
    "valor título) por período de vencimento e, opcionalmente, por fornecedor"
)
CACHE_FREQUENCY = "daily"
CREATED_BY = "jose"
CONNECTION = {
    "host": "localhost",
    "port": 1433,
    "database": "SedareDB",
    "user": "sa",
    "sslmode": "prefer",  # Encrypt=yes;TrustServerCertificate=yes
    # Na máquina de dev só o ODBC Driver 17 está instalado (F11 §7.2)
    "driver": "ODBC Driver 17 for SQL Server",
}

# Subconjunto comum de SQL (F11 §8.4): sem ORDER BY de topo, sem ';', colunas com nome único
STEP_SQL = (
    "SELECT Fornecedor.Nome Fornecedor, "
    "TituloPagar.DataVencimento, "
    "TituloPagar.ValorReceita, "
    "TituloPagar.ValorDespesa, "
    "TituloPagar.ValorTitulo "
    "FROM TituloPagar "
    "INNER JOIN Fornecedor ON Fornecedor.Id = TituloPagar.FornecedorId "
    "WHERE TituloPagar.DataVencimento >= :DATA_INI "
    "AND TituloPagar.DataVencimento <= :DATA_FIM "
    "AND (Fornecedor.Nome = :FORNECEDOR OR :FORNECEDOR IS NULL)"
)
STEP_PARAMS = ["DATA_INI", "DATA_FIM", "FORNECEDOR"]

PARAMETERS = {
    "DATA_INI": {
        "type": "date",
        "required": True,
        "description": "Data de vencimento inicial (YYYY-MM-DD), inclusiva",
    },
    "DATA_FIM": {
        "type": "date",
        "required": True,
        "description": "Data de vencimento final (YYYY-MM-DD), inclusiva",
    },
    "FORNECEDOR": {
        "type": "string",
        "required": False,
        "description": "Nome exato do fornecedor; omitir para todos",
    },
}


def sql_literal(value: str) -> str:
    """Literal SQL entre aspas simples (escapa ' como '')."""
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # o .sql gerado em redirect não sai em cp1252
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--password", help="senha do SQL Server (se omitida, é pedida)")
    args = parser.parse_args()
    password = args.password or getpass.getpass("Senha do SQL Server: ")

    data_source_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    step_id = str(uuid.uuid4())

    connection_config = {**CONNECTION, "password": encrypt_password(password)}
    step_definition = {"sql": STEP_SQL, "params": STEP_PARAMS}

    print("-- ================================================================")
    print("-- Cadastro do data_source SQL Server e da analise")
    print(f"-- '{ANALYSIS_NAME}' -- rodar no banco de CONFIG (analysis_config).")
    print(f"-- data_source_id: {data_source_id}")
    print(f"-- analysis_id:    {analysis_id}")
    print("-- ================================================================\n")

    print(f"""INSERT INTO data_sources (id, name, type, connection_config, is_active, created_by)
VALUES (
    '{data_source_id}',
    {sql_literal(DATA_SOURCE_NAME)},
    'sqlserver',
    {sql_literal(json.dumps(connection_config))}::jsonb,
    true,
    {sql_literal(CREATED_BY)}
);
""")

    print(f"""INSERT INTO analyses (id, name, description, data_source_id, cache_frequency, parameters, is_active, created_by)
VALUES (
    '{analysis_id}',
    {sql_literal(ANALYSIS_NAME)},
    {sql_literal(ANALYSIS_DESCRIPTION)},
    '{data_source_id}',
    {sql_literal(CACHE_FREQUENCY)},
    {sql_literal(json.dumps(PARAMETERS))}::jsonb,
    true,
    {sql_literal(CREATED_BY)}
);
""")

    print(f"""INSERT INTO analysis_steps (id, analysis_id, step_order, step_type, definition)
VALUES (
    '{step_id}',
    '{analysis_id}',
    1,
    'query',
    {sql_literal(json.dumps(step_definition))}::jsonb
);
""")


if __name__ == "__main__":
    main()
