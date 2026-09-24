-- Banco: analysis_config (PostgreSQL local)

-- Tabela 1: Fontes de Dados
CREATE TABLE data_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    type VARCHAR(50) NOT NULL,  -- postgresql, mysql, sqlserver, mongodb, api
    connection_config JSONB NOT NULL,  -- {host, port, database, ...}
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 2: Análises (definições)
CREATE TABLE analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    data_source_id UUID REFERENCES data_sources(id),
    cache_frequency VARCHAR(50) DEFAULT 'daily',
    parameters JSONB,  -- schema dos parâmetros aceitos
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 3: Etapas da Análise
CREATE TABLE analysis_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    step_order INT NOT NULL,
    step_type VARCHAR(50) NOT NULL,  -- query, transform, aggregate
    definition JSONB NOT NULL,  -- {sql, handler, params, ...}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(analysis_id, step_order)
);

-- Tabela 4: Versões de Análises
CREATE TABLE analysis_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id UUID NOT NULL REFERENCES analyses(id),
    version_number INT NOT NULL,
    full_definition JSONB NOT NULL,  -- snapshot completo
    changes_summary TEXT,
    changed_by VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(analysis_id, version_number)
);

-- Tabela 5: Histórico de Execuções (Simplificado — sem identificação de usuário/cliente)
CREATE TABLE execution_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id UUID NOT NULL REFERENCES analyses(id),
    analysis_version_id UUID REFERENCES analysis_versions(id),

    parameters JSONB,
    status VARCHAR(50),  -- success, failed, timeout
    execution_time_ms INT,
    rows_affected INT,
    result_size_bytes INT,
    error_message TEXT,
    result_location VARCHAR(500),  -- path/uri do resultado
    executed_at TIMESTAMP DEFAULT NOW(),
    cached BOOLEAN DEFAULT false
);

-- Índices para performance
CREATE INDEX idx_analyses_active ON analyses(is_active);
CREATE INDEX idx_execution_history_analysis ON execution_history(analysis_id);
CREATE INDEX idx_execution_history_executed_at ON execution_history(executed_at);
CREATE INDEX idx_versions_analysis ON analysis_versions(analysis_id);