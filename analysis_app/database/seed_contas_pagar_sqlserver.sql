-- ================================================================
-- Cadastro do data_source SQL Server e da analise
-- 'contas_a_pagar_por_fornecedor' -- rodar no banco de CONFIG (analysis_config).
-- data_source_id: 2f8f0918-e964-4ccc-b164-ede2f0224143
-- analysis_id:    e1410687-7432-4692-9887-ec7a1ff0621f
-- ================================================================

BEGIN;

INSERT INTO data_sources (id, name, type, connection_config, is_active, created_by)
VALUES (
    '2f8f0918-e964-4ccc-b164-ede2f0224143',
    'sedare_sqlserver',
    'sqlserver',
    '{"host": "localhost", "port": 1433, "database": "SedareDB", "user": "sa", "sslmode": "prefer", "driver": "ODBC Driver 18 for SQL Server", "password": "gAAAAABqvFEBIggiE831jPQtOHvCHAsQsu4F7JhxMM6EkogRg2UER7DFOvLq8d4CxHVhi3PJ9z8Er_zhUN-g3l_eLdKlUjQuzg=="}'::jsonb,
    true,
    'jose'
);

INSERT INTO analyses (id, name, description, data_source_id, cache_frequency, parameters, is_active, created_by)
VALUES (
    'e1410687-7432-4692-9887-ec7a1ff0621f',
    'contas_a_pagar_por_fornecedor',
    'Retorna títulos a pagar (fornecedor, vencimento, valor receita, valor despesa, valor título) por período de vencimento e, opcionalmente, por trecho do nome do fornecedor',
    '2f8f0918-e964-4ccc-b164-ede2f0224143',
    'daily',
    '{"DATA_INI": {"type": "date", "required": true, "description": "Data de vencimento inicial (YYYY-MM-DD), inclusiva"}, "DATA_FIM": {"type": "date", "required": true, "description": "Data de vencimento final (YYYY-MM-DD), inclusiva"}, "FORNECEDOR": {"type": "string", "required": false, "description": "Parte do nome do fornecedor (busca por trecho, sem diferenciar curingas % e _); omitir para todos"}}'::jsonb,
    true,
    'jose'
);

INSERT INTO analysis_steps (id, analysis_id, step_order, step_type, definition)
VALUES (
    '8155efc7-5c54-4ed0-9fe1-3ae0d2edabfd',
    'e1410687-7432-4692-9887-ec7a1ff0621f',
    1,
    'query',
    '{"sql": "SELECT Fornecedor.Nome Fornecedor, TituloPagar.DataVencimento, TituloPagar.ValorReceita, TituloPagar.ValorDespesa, TituloPagar.ValorTitulo FROM TituloPagar INNER JOIN Fornecedor ON Fornecedor.Id = TituloPagar.FornecedorId WHERE TituloPagar.DataVencimento >= :DATA_INI AND TituloPagar.DataVencimento <= :DATA_FIM AND (Fornecedor.Nome LIKE ''%'' + :FORNECEDOR + ''%'' OR :FORNECEDOR IS NULL)", "params": ["DATA_INI", "DATA_FIM", "FORNECEDOR"]}'::jsonb
);

COMMIT;
