#!/usr/bin/env python3
"""
Gera os INSERTs SQL para cadastrar a primeira análise de teste do F4
("vendas_por_periodo"), cifrando a senha do data_source com Fernet
antes de montar o SQL (ver ARQUITETURA.md §8.2).

Uso:
    cd analysis_app
    python scripts/seed_analise_vendas.py > seed_vendas.sql

Pré-requisito: FERNET_KEY já definida no .env do projeto (gerada com
Fernet.generate_key(), fora do repositório — ver ARQUITETURA.md §5.1/§8.2).
Se ainda não existir, o script gera uma chave nova e para para você
salvá-la no .env antes de rodar de novo.

IMPORTANTE: os 3 INSERTs abaixo são para o banco de CONFIG
(analysis_config — schema criado manualmente no F2), NÃO para o
banco "data_db" (esse é apenas o data source que será consultado
em tempo de execução pela análise).

Convenção de parâmetros nomeados usada no SQL do STEP (":nome"):
proposta para este script — o Execution Engine (F4) ainda precisa
traduzir ":data_inicial", ":data_final", ":pago" para os placeholders
posicionais ($1, $2, $3) que o asyncpg exige, na ordem definida em
"params". Sinalizando aqui porque essa tradução ainda não está
formalizada em nenhum documento — vale confirmar antes de eu colocar
isso como decisão fechada na spec do F4.
"""
import json
import os
import uuid

from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

FERNET_KEY = os.getenv("FERNET_KEY")
if not FERNET_KEY:
    nova_chave = Fernet.generate_key().decode()
    print("AVISO: FERNET_KEY nao encontrada no .env.", flush=True)
    print("Gerei uma chave nova -- salve no .env antes de rodar novamente:", flush=True)
    print(f"FERNET_KEY={nova_chave}", flush=True)
    raise SystemExit(1)

fernet = Fernet(FERNET_KEY.encode())

# --- 1. Data Source: banco "data_db" (usuario chronus) ---
data_source_id = str(uuid.uuid4())
senha_plana = "Senha123"
senha_cifrada = fernet.encrypt(senha_plana.encode()).decode()

connection_config = {
    "host": "localhost",
    "port": 5432,
    "database": "data_db",
    "user": "chronus",
    "password": senha_cifrada,
    "sslmode": "prefer",
}

sql_data_source = f"""
INSERT INTO data_sources (id, name, type, connection_config, is_active, created_by)
VALUES (
    '{data_source_id}',
    'vendas_db_local',
    'postgresql',
    '{json.dumps(connection_config)}'::jsonb,
    true,
    'jose'
);
"""

# --- 2. Analysis: vendas_por_periodo ---
analysis_id = str(uuid.uuid4())
parameters = {
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
        "description": "Filtrar por status de pagamento (true=pagas, false=nao pagas); omitir para todas",
    },
}

sql_analysis = f"""
INSERT INTO analyses (id, name, description, data_source_id, cache_frequency, parameters, is_active, created_by)
VALUES (
    '{analysis_id}',
    'vendas_por_periodo',
    'Retorna vendas (data, valor, pago) filtradas por periodo e, opcionalmente, status de pagamento',
    '{data_source_id}',
    'daily',
    '{json.dumps(parameters)}'::jsonb,
    true,
    'jose'
);
"""

# --- 3. Analysis Step: query unica (STEP 1) ---
step_id = str(uuid.uuid4())
step_definition = {
    "sql": (
        "SELECT data, valor, pago FROM vendas "
        "WHERE data BETWEEN :data_inicial AND :data_final "
        "AND (:pago IS NULL OR pago = :pago) "
        "ORDER BY data"
    ),
    "params": ["data_inicial", "data_final", "pago"],
}

sql_step = f"""
INSERT INTO analysis_steps (id, analysis_id, step_order, step_type, definition)
VALUES (
    '{step_id}',
    '{analysis_id}',
    1,
    'query',
    '{json.dumps(step_definition)}'::jsonb
);
"""

print("-- ================================================================")
print("-- Cadastro da analise 'vendas_por_periodo' -- rodar no banco de")
print("-- CONFIG (analysis_config), NAO no banco data_db.")
print("-- data_source_id gerado:", data_source_id)
print("-- analysis_id gerado:   ", analysis_id)
print("-- ================================================================\n")
print(sql_data_source)
print(sql_analysis)
print(sql_step)
