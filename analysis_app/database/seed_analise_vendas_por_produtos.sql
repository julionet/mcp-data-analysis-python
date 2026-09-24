-- ================================================================
-- Cadastro da analise 'vendas_por_produtos' -- rodar no banco de
-- CONFIG (analysis_config), NAO no banco data_db.
-- Reaproveita o data_source_id ja registrado para 'vendas_db_local'
-- (ver database/seed_vendas.sql).
-- ================================================================

WITH new_analysis AS (
    INSERT INTO analyses (name, description, data_source_id, cache_frequency, parameters, is_active, created_by)
    VALUES (
        'vendas_por_produtos',
        'Retorna itens de venda (data, produto, quantidade, valor, total) filtrados por periodo e, opcionalmente, por produto',
        '481e1af0-cb9c-4dd4-ab7a-71ca7b26496d',
        'daily',
        '{"data_inicial": {"type": "date", "required": true, "description": "Data inicial do periodo (YYYY-MM-DD)"}, "data_final": {"type": "date", "required": true, "description": "Data final do periodo (YYYY-MM-DD)"}, "produto": {"type": "string", "required": false, "description": "Filtro por descricao do produto (busca parcial, case-insensitive); omitir para todos"}}'::jsonb,
        true,
        'jose'
    )
    RETURNING id
)
INSERT INTO analysis_steps (analysis_id, step_order, step_type, definition)
SELECT
    id,
    1,
    'query',
    '{"sql": "SELECT vendas.data, produtos.descricao produto, vendas_item.quantidade, vendas_item.valor, vendas_item.total FROM vendas_item INNER JOIN produtos ON produtos.id = vendas_item.produto_id INNER JOIN vendas ON vendas.id = vendas_item.vend_id WHERE vendas.data BETWEEN :data_inicial AND :data_final AND (:produto::text IS NULL OR produtos.descricao ILIKE ''%'' || :produto || ''%'') ORDER BY vendas.data", "params": ["data_inicial", "data_final", "produto"]}'::jsonb
FROM new_analysis;
