-- Banco: analysis_config (PostgreSQL local)

-- Tabela 1: Fontes de Dados
CREATE TABLE data_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    type VARCHAR(50) NOT NULL,  -- postgresql, mysql, sqlserver, oracle, api
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

-- Tabela 4: Usuários (F12)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    external_id VARCHAR(255) UNIQUE,   -- e-mail de login, cadastrado SEMPRE em minúsculas
    password_hash VARCHAR(255),        -- hash bcrypt ($2b$...); NULL = não consegue emitir token
    is_blocked BOOLEAN NOT NULL DEFAULT false,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 5: Perfis (F12)
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 6: Usuário N:N Perfil (F12)
CREATE TABLE user_profiles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, profile_id)
);

-- Tabela 7: Perfil N:N Análise (F12)
CREATE TABLE profile_analyses (
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    analysis_id UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    PRIMARY KEY (profile_id, analysis_id)
);

-- Tabela 8: Tokens de acesso opacos, só o hash SHA-256 (F12)
CREATE TABLE access_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    label VARCHAR(255),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

-- Tabela 9: Histórico de Execuções (user_id: quem executou — F12; NULL em linhas pré-F12)
CREATE TABLE execution_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id UUID NOT NULL REFERENCES analyses(id),

    parameters JSONB,
    status VARCHAR(50),  -- success, failed, timeout
    execution_time_ms INT,
    rows_affected INT,
    result_size_bytes INT,
    error_message TEXT,
    result_location VARCHAR(500),  -- path/uri do resultado
    executed_at TIMESTAMP DEFAULT NOW(),
    cached BOOLEAN DEFAULT false,
    user_id UUID REFERENCES users(id)  -- sem ON DELETE: preserva auditoria (F12)
);

-- Índices para performance
CREATE INDEX idx_analyses_active ON analyses(is_active);
CREATE INDEX idx_execution_history_analysis ON execution_history(analysis_id);
CREATE INDEX idx_execution_history_executed_at ON execution_history(executed_at);
CREATE INDEX idx_access_tokens_user ON access_tokens(user_id);
CREATE INDEX idx_execution_history_user ON execution_history(user_id);
