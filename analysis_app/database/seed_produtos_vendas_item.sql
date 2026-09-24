-- ================================================================
-- Novas tabelas de teste no banco data_db: produtos e vendas_item.
-- vendas_item.vend_id referencia vendas.id (tabela ja existente,
-- criada manualmente fora deste repo).
-- Rodar em: data_db (NAO no analysis_config).
-- ================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS produtos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    descricao VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS vendas_item (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vend_id UUID NOT NULL REFERENCES vendas(id),
    produto_id UUID NOT NULL REFERENCES produtos(id),
    quantidade DOUBLE PRECISION NOT NULL,
    valor DOUBLE PRECISION NOT NULL,
    total DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vendas_item_vend_id ON vendas_item(vend_id);
CREATE INDEX IF NOT EXISTS idx_vendas_item_produto_id ON vendas_item(produto_id);

-- --------------------------------------------------------------
-- Produtos (10)
-- --------------------------------------------------------------
INSERT INTO produtos (descricao) VALUES
    ('Notebook 14"'),
    ('Mouse sem fio'),
    ('Teclado mecanico'),
    ('Monitor 24"'),
    ('Cadeira de escritorio'),
    ('Webcam HD'),
    ('Headset Bluetooth'),
    ('Impressora laser'),
    ('HD externo 1TB'),
    ('Carregador USB-C');

-- --------------------------------------------------------------
-- Vendas + itens: 20 vendas, 4 ou 5 itens cada, valores aleatorios.
-- vendas.valor e recalculado como soma dos itens ao final de cada venda.
-- --------------------------------------------------------------
DO $$
DECLARE
    v_venda_id UUID;
    v_qtd_itens INT;
    v_quantidade NUMERIC(10, 2);
    v_valor_unit NUMERIC(10, 2);
    v_total NUMERIC(10, 2);
    v_produto_id UUID;
    produto_ids UUID[];
    i INT;
    j INT;
BEGIN
    SELECT array_agg(id) INTO produto_ids FROM produtos;

    FOR i IN 1..20 LOOP
        INSERT INTO vendas (data, valor, pago)
        VALUES (
            CURRENT_DATE - (floor(random() * 90))::int,
            0,
            (random() < 0.7)
        )
        RETURNING id INTO v_venda_id;

        v_qtd_itens := 4 + floor(random() * 2)::int; -- 4 ou 5

        FOR j IN 1..v_qtd_itens LOOP
            v_produto_id := produto_ids[1 + floor(random() * array_length(produto_ids, 1))::int];
            v_quantidade := 1 + floor(random() * 5);
            v_valor_unit := round((20 + random() * 180)::numeric, 2);
            v_total := round(v_quantidade * v_valor_unit, 2);

            INSERT INTO vendas_item (vend_id, produto_id, quantidade, valor, total)
            VALUES (v_venda_id, v_produto_id, v_quantidade, v_valor_unit, v_total);
        END LOOP;

        UPDATE vendas
        SET valor = (SELECT COALESCE(SUM(total), 0) FROM vendas_item WHERE vend_id = v_venda_id)
        WHERE id = v_venda_id;
    END LOOP;
END $$;
