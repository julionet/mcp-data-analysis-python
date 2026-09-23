"""Dados fake em memória — substitui PostgreSQL + execution_history do F0 (Sprint 0)."""

ANALYSES = {
    "vendas_por_regiao": {
        "id": "vendas_por_regiao",
        "description": (
            "Retorna o total de vendas de um mês, agrupado por região "
            "(Sudeste, Sul, Nordeste), ordenado da maior para a menor, com a "
            "região de maior venda marcada com destaque. Use esta ferramenta "
            "sempre que o usuário perguntar sobre vendas, faturamento ou "
            "desempenho comercial por região, estado ou mês."
        ),
        "parameters": {"mes": "string"},
    }
}

FAKE_ROWS = [
    {"regiao": "Sudeste", "vendas": 15000},
    {"regiao": "Sul", "vendas": 8000},
    {"regiao": "Nordeste", "vendas": 6500},
]

EXECUTION_LOG: list[dict] = []  # substitui execution_history — perdido no restart
