# 🏗️ Documento de Arquitetura

## Plataforma de Análise de Dados Genérica com MCP

**Versão:** 1.10 (Aprovado — Streamable HTTP **com TLS obrigatório** Multi-Cliente, sem autenticação em V1.0, com PostgreSQL + MySQL + SQL Server + MongoDB, **sem Handlers — servidor entrega dataset bruto**)
**Data:** 2026-09-24
**Stack:** FastAPI + Python + PostgreSQL + MCP
**Status:** ✅ Aprovado

> **Nota de revisão (v1.9 → v1.10):** F5 (MCP Tools Integration) implementada — `list_tools()`/`call_tool()` reais em `mcp_transport/tools.py`, consumindo `AnalysisService`/`AnalysisRepository.get_by_name()` (F5_MCP_TOOLS_INTEGRATION.md). Duas correções de nomenclatura/contrato aplicadas retroativamente em toda a documentação (§3.4, F3, F4) para bater com o texto já aprovado da spec F5: (1) o status de recusa por volume passa a se chamar **`volume_exceeded`** (era `refinamento_necessario` desde a v1.9 — mesmo formato de payload, só o nome do status mudou); (2) `AnalysisService.execute()` deixa de propagar exceção — todo caminho de saída é um dict `{"status": "success"|"volume_exceeded"|"error", ...}`, e o parâmetro `confirmar_volume_alto` agora é aceito diretamente por `execute()` (bypass real dos dois checks de volume, com `"aviso"` no payload de sucesso).
>
> **Nota de revisão (v1.8 → v1.9):** documento aprovado. Removida inteiramente a camada de **Handlers Python** do servidor — `HandlerRegistry`, pasta `handlers/`, `HandlerRepository`, ADR-005 e a tabela `custom_handlers` do schema (decisão: remover, não manter tabela sem uso — o projeto ainda não está em produção, então não há risco de `DROP TABLE` destrutivo). O servidor deixa de transformar dados: executa a query parametrizada e devolve o **dataset bruto** ao cliente MCP, que interpreta/agrega os dados do lado do LLM. Em troca, ganha uma nova camada de **Controle de Volume** (`VolumeGuardService`): pré-checagem via `SELECT COUNT(*)`, checagem de tamanho serializado em KB, e recusa estruturada com pedido de refinamento (ou confirmação explícita via parâmetro reservado `confirmar_volume_alto`) — ver nova seção **§3.4**. Limites (`DEFAULT_MAX_RESULT_ROWS`, `DEFAULT_MAX_RESULT_SIZE_KB`) são 100% globais via `.env`, sem override por análise. Atualizados: §1.2, §2.1, §2.2 (schema), nova §2.3 (formato de `analyses.parameters` e conversão para JSON Schema MCP), §3.1, §3.2, nova §3.4, §4.3 (era Registry Pattern, agora Volume Guard), §5.1 (`cryptography`/Fernet), §5.2 (estrutura de pastas), §6.1 (startup), §7 (ADR-005 reescrito), §8.2 (formaliza Fernet para `connection_config.password`), §10.3, §11, §13, §14. Ver `PROPOSTA_REVISAO_HANDLERS_E_VOLUME.md` para o racional completo e NEGOCIO.md v1.6 / FEATURES_ROADMAP.md v1.6 para as mudanças correspondentes nos outros documentos.

> **Nota de revisão (v1.1 → v1.2):** removidos `ClientIdentificationService`, `UserIdentificationService`, as tabelas `mcp_clients`, `users`, `user_api_keys`, e os ADRs de autenticação (eram ADR-007 e ADR-008). O transporte deixou de ser descrito como stdio (subprocesso local por usuário) e passou a ser **HTTP+SSE**, um único serviço na rede interna acessível por múltiplos clientes MCP simultaneamente. Também corrigida a ordem de criação de tabelas no schema (havia uma FK para uma tabela definida mais adiante) e a numeração duplicada de seções (havia duas seções "12" e duas "13").

> **Nota de revisão (v1.2 → v1.3):** documento aprovado. Adicionado **SQLServerAdapter** como adapter de primeira classe em V1.0 (via ODBC/`aioodbc`), ao lado de PostgreSQL, MySQL e MongoDB (ver §2.1, §4.2, §5.1, §13).

> **Nota de revisão (v1.3 → v1.4):** documento aprovado. Trocado o transporte MCP de **HTTP+SSE** (endpoint `/sse`) para **Streamable HTTP** (endpoint único `/mcp`), o transporte mais recente da especificação MCP. Atualizados: ADR-006 (§7), diagrama de contexto (§1.1), topologia local (§1.2), exemplo de configuração de cliente, stack técnico (§5.1 — dependência `mcp` do SDK), estrutura de pastas (§5.2) e fluxo de inicialização (§6.1). Porta permanece 3000; nenhuma outra decisão de arquitetura foi alterada.

> **Nota de revisão (v1.4 → v1.5):** documento aprovado. O protótipo F0 (`F0_PROTOTIPO_MCP_MEMORIA.md`) validou a decisão do ADR-006 na prática e revelou 4 ajustes técnicos necessários para o F1 real: (1) **TLS agora é obrigatório mesmo em rede interna** — clientes MCP reais (confirmado: Claude Desktop) recusam conector remoto via `http://` simples, independente da rede ser confiável; (2) a dependência `mcp` precisa de teto de versão — a v2.0.0 do SDK remove os decorators `list_tools()`/`call_tool()` da classe de baixo nível `Server` usada no ADR-006; (3) o handshake TLS precisa negociar ALPN explicitamente (a CLI padrão do uvicorn não faz isso, exigindo `ssl_context_factory` programático); (4) o endpoint MCP montado via `app.mount()` sob FastAPI precisa de uma rota exata adicional para o path sem barra final, evitando um redirect 307 que alguns clientes não toleram bem. Atualizados: ADR-006 (§7), §5.1 (dependências), §9.1 (plano de implantação local), nova nota em §6.1.

> **Nota de revisão (v1.5 → v1.6):** documento aprovado. Adicionada uma nova seção **§9.2 Produção Interna (nginx + Certbot)** — um servidor de produção dedicado, ainda em rede interna (Restrição T1 continua valendo), usando nginx como reverse proxy para terminação TLS e Certbot para emissão/renovação de certificado. Documentadas as duas estratégias possíveis para o Certbot: desafio DNS-01 contra um domínio público (não exige expor o servidor à internet, só o DNS do domínio) ou uma CA interna própria compatível com ACME (sem depender de domínio público, mas exige instalar essa CA em cada máquina cliente). A antiga §9.2 (Remoto — Futuro, Kubernetes) foi renumerada para §9.3. Nenhuma outra decisão de arquitetura foi alterada — o app continua servindo `/mcp` sem autenticação (ADR-006).

> **Nota de revisão (v1.6 → v1.7):** documento aprovado. Explicitada em §9.2 a diferença de exigência de confiança do cliente entre as duas opções de Certbot: a Opção A (DNS-01/Let's Encrypt) não exige nenhuma configuração nos clientes MCP, porque a CA do Let's Encrypt já vem pré-instalada por padrão em qualquer sistema operacional/runtime — igual a qualquer API pública comum; a Opção B (CA interna) exige instalar/confiar nessa CA em cada máquina cliente, exatamente como o mkcert em §9.1. A distinção não é "nginx+Certbot vs. mkcert", é se a CA emissora já é publicamente confiável de fábrica ou é uma CA privada criada para esse ambiente.

> **Nota de revisão (v1.7 → v1.8):** documento aprovado. Renomeada em §5.2 a pasta `mcp/` para **`mcp_transport/`** — durante a implementação de F1 (`F1_IMPLEMENTACAO.md`), constatou-se que um pacote local chamado `mcp/` colide com o SDK `mcp` que ele mesmo importa (`from mcp.server.lowlevel import Server`): rodando o processo a partir de `analysis_app/` (padrão usado desde o protótipo F0), o Python resolve `import mcp` para o pacote local em vez do SDK instalado, quebrando com `ModuleNotFoundError: No module named 'mcp.server'`. Nenhuma outra decisão de arquitetura foi alterada — apenas o nome da pasta em §5.2.

---

## 1. Visão Arquitetural

### 1.1 Contexto Geral

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Claude Desktop │  │  Gemini Desktop │  │ OpenAI Desktop  │  ... (qualquer cliente MCP)
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                     │
         └────────────────────┼─────────────────────┘
                               │  Streamable HTTP (mesma porta, mesma instância)
                               ▼
┌─────────────────────────────────────────────────────────┐
│           FastAPI MCP Server (Port 3000, Streamable HTTP)       │
│  ├─ Discovery: lista análises dinâmicas                 │
│  ├─ Execution: executa análise selecionada              │
│  └─ Logging: registra execuções (sem identificação)     │
└─────────────────────────────────────────────────────────┘
            ↓              ↓              ↓              ↓
      ┌───────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐
      │PostgreSQL │  │  MySQL   │  │SQL Server │  │   MongoDB    │
      │(Config+DB)│  │(Data Src)│  │(Data Src) │  │ (Data Source)│
      └───────────┘  └──────────┘  └───────────┘  └──────────────┘
```

**Ponto-chave:** o servidor é um **processo HTTP persistente** (`uvicorn main:app --host 0.0.0.0 --port 3000`), não um subprocesso disparado por `command`/`args` de um cliente MCP. Cada cliente se conecta como **conector remoto** (URL), e vários clientes — inclusive de fabricantes diferentes — podem estar conectados ao mesmo tempo.

### 1.2 Topologia Local vs Remoto

#### **Local (Rede Interna — Multi-Cliente, Sem Autenticação)**
```
┌────────────────────────────────────────┐
│   Máquina na Rede Interna              │
│  ├─ Processo uvicorn (porta 3000)     │
│  │  ├─ FastAPI Server                 │
│  │  ├─ MCP Interface (Streamable HTTP)       │
│  │  └─ Volume Guard (pré-check)       │
│  ├─ PostgreSQL (config)                │
│  └─ PostgreSQL (data source)           │
└────────────────────────────────────────┘
     ↑                ↑                ↑
Claude Desktop   Gemini Desktop    OpenAI Desktop
(conector remoto)(conector remoto) (conector remoto)
(via Streamable HTTP)   (via Streamable HTTP)    (via Streamable HTTP)

Nota: qualquer cliente MCP compatível com Streamable HTTP funciona,
sem necessidade de headers de autenticação em V1.0.
```

**Exemplo de configuração no cliente (formato varia por app, mas o conceito é o mesmo):**
```json
{
  "mcpServers": {
    "analysis": {
      "url": "https://192.168.1.50:3000/mcp"
    }
  }
}
```

> `https://`, não `http://` — TLS é obrigatório mesmo em rede interna (ver ADR-006). Certificado confiável nas máquinas clientes: mkcert (máquina única) ou CA interna instalada em cada cliente (múltiplas máquinas).
Sem `command`, `args` ou `env` — o servidor já está rodando de forma independente na rede; o cliente só aponta para a URL.

#### **Remoto (Produção — Futuro)**
```
                    ┌─────────────────────────────────────┐
                    │     Qualquer cliente MCP (via HTTP)  │
                    │ ├─ Claude Desktop / API              │
                    │ ├─ Gemini Desktop / API              │
                    │ ├─ OpenAI Desktop / API               │
                    │ └─ Novos clientes (futuros)          │
                    └────────────┬──────────────────────────┘
                                 ↓
┌──────────────────────────────────────────────────────┐
│         Kubernetes Cluster (HA)                      │
│  ┌────────────────────────────────────────────┐    │
│  │ FastAPI MCP Servers (replicas)             │    │
│  │  ├─ MCP Interface (Streamable HTTP)               │    │
│  │  └─ Volume Guard (pré-check)                │    │
│  ├────────────────────────────────────────────┤    │
│  │ Celery Workers (replicas)                  │    │
│  │  └─ Execução de queries pesadas/demoradas  │    │
│  ├────────────────────────────────────────────┤    │
│  │ Redis Cluster (Cache + Task Queue)         │    │
│  ├────────────────────────────────────────────┤    │
│  │ PostgreSQL (HA) — Config DB                │    │
│  └────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘

⚠️ Ao expor remotamente (fora da rede confiável), autenticação e
identificação de cliente/usuário DEVEM ser reintroduzidas (ver §12).
```

---

## 2. Componentes Principais

### 2.1 Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Application                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │    MCP Server Interface (Streamable HTTP, Multi-Cliente)   │   │
│  │                                                      │   │
│  │  Aceita de QUALQUER cliente MCP compatível          │   │
│  │  com Streamable HTTP, simultaneamente, sem autenticação:   │   │
│  │  ├─ Claude Desktop                                  │   │
│  │  ├─ Gemini Desktop                                  │   │
│  │  ├─ OpenAI Desktop                                  │   │
│  │  └─ Qualquer futuro cliente com MCP padrão          │   │
│  │                                                      │   │
│  │  Endpoints Padrão MCP:                             │   │
│  │  ├─ list_tools()         → todas análises          │   │
│  │  ├─ call_tool()          → executa análise         │   │
│  │  ├─ list_resources()     → lista recursos          │   │
│  │  └─ read_resource()      → detalhes do recurso     │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Services (Business Logic)                  │   │
│  │  ├─ AnalysisService                                │   │
│  │  │  ├─ execute(analysis_id, params)                │   │
│  │  │  ├─ get_all_analyses()                          │   │
│  │  │  └─ validate_analysis(schema)                   │   │
│  │  ├─ VolumeGuardService                             │   │
│  │  │  ├─ check_row_count(sql, params)                │   │
│  │  │  ├─ check_serialized_size(result)                │   │
│  │  │  └─ build_refinement_response(estimate, limit)   │   │
│  │  ├─ CacheService                                   │   │
│  │  │  ├─ get_or_execute(analysis_id, params)         │   │
│  │  │  └─ invalidate_by_source(source_id)             │   │
│  │  ├─ VersionService                                 │   │
│  │  │  ├─ get_history(analysis_id)                    │   │
│  │  │  ├─ rollback(analysis_id, version)              │   │
│  │  │  └─ diff_versions(v1, v2)                       │   │
│  │  └─ AuditService (Simplificado — sem usuário/cliente)│  │
│  │     ├─ log_execution(analysis_id, params, result)  │   │
│  │     └─ get_execution_history()                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Adapters (Database Access)                 │   │
│  │  ├─ DatabaseAdapter (Abstract)                     │   │
│  │  ├─ PostgreSQLAdapter                              │   │
│  │  ├─ MongoDBAdapter                                 │   │
│  │  ├─ MySQLAdapter                                   │   │
│  │  ├─ SQLServerAdapter                               │   │
│  │  └─ APIAdapter                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Data Access (Repository)                   │   │
│  │  ├─ AnalysisRepository                             │   │
│  │  ├─ DataSourceRepository                           │   │
│  │  ├─ VersionRepository                              │   │
│  │  └─ ExecutionRepository                            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Banco de Dados — Schema

> Ordem de criação corrigida: nenhuma tabela referencia outra que ainda não existe.

```sql
-- Banco: analysis_config (PostgreSQL local)

-- Tabela 1: Fontes de Dados
CREATE TABLE data_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    type VARCHAR(50) NOT NULL,  -- postgresql, mysql, sqlserver, mongodb, api
    connection_config JSONB NOT NULL,  -- {host, port, database, user, password (Fernet), sslmode} — ver §8.2
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
    step_type VARCHAR(50) NOT NULL,  -- query (único tipo em uso em V1.0; coluna mantida
                                      -- para permitir múltiplas queries por análise)
    definition JSONB NOT NULL,  -- {sql, params, ...}
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
```

> As tabelas `mcp_clients`, `users` e `user_api_keys`, e as colunas `user_id`, `username`, `client_llm_name`, `client_llm_version`, `client_identifier` em `execution_history`, foram removidas de V1.0. A especificação completa delas (com código de middleware, repositórios etc.) fica preservada como referência para quando esse requisito voltar ao escopo — ver §12 Roadmap Arquitetural.
>
> A tabela `custom_handlers` também foi removida do schema (revisão v1.9) — a camada de Handlers Python deixou de existir; ver nota de revisão no topo do documento e `PROPOSTA_REVISAO_HANDLERS_E_VOLUME.md`.

---

### 2.3 Formato de `analyses.parameters` e Conversão para JSON Schema MCP

O campo `analyses.parameters` (JSONB, §2.2 Tabela 2) segue um formato fixo por parâmetro:

```json
{
  "<nome_parametro>": {
    "type": "string | integer | number | boolean | date | datetime",
    "required": true,
    "description": "Texto que explica o parâmetro — usado pelo LLM pra saber o que perguntar ao usuário",
    "default": null,
    "enum": ["valor1", "valor2"],
    "min": null,
    "max": null
  }
}
```

**Exemplo real (`vendas_por_regiao`):**
```json
{
  "data_inicial": { "type": "date", "required": true, "description": "Data inicial do período de vendas (YYYY-MM-DD)" },
  "data_final": { "type": "date", "required": true, "description": "Data final do período de vendas (YYYY-MM-DD)" },
  "regiao": { "type": "string", "required": false, "description": "Filtrar por uma região específica", "enum": ["Norte", "Sul", "Leste", "Oeste", "Centro"] }
}
```

**Módulo compartilhado** (usado por F5 — `list_tools` — e pelo Execution Engine F4, mesma fonte de verdade, sem duplicar regras):
```
schemas/analysis_parameters.py
├─ to_json_schema(parameters: dict) -> dict
│     # usado por F5 (list_tools) — gera o inputSchema padrão MCP
└─ to_pydantic_model(parameters: dict) -> Type[BaseModel]
      # usado pelo Execution Engine (F4) — valida antes de executar
```

**Mapeamento de tipos** (`type` interno → JSON Schema):

| `type` (interno) | JSON Schema `type` | JSON Schema `format` |
|---|---|---|
| string | string | — |
| integer | integer | — |
| number | number | — |
| boolean | boolean | — |
| date | string | date |
| datetime | string | date-time |

> O parâmetro reservado `confirmar_volume_alto` (§3.4) não passa por este módulo — é injetado
> diretamente pelo `mcp_transport/tools.py` no `inputSchema` de toda tool, por ser global.

---

## 3. Fluxos de Dados

### 3.1 Fluxo: Descoberta de Análises

```
┌──────────────────┐
│ Qualquer Cliente │
│ MCP conecta via  │
│ Streamable HTTP         │
└────────┬──────────┘
         │
         ├─ MCP Call: list_tools()
         │
┌────────▼────────────────────────────┐
│   FastAPI MCP Server                │
│  list_tools() endpoint               │
│  ├─ 1. AnalysisService.get_all()   │
│  │    └─ Query: SELECT * analyses   │
│  └─ 2. Retorna JSON schema          │
└────────┬────────────────────────────┘
         │
         ├─ [análise_1, análise_2, ...]
         │
┌────────▼────────────────────────┐
│ Cliente MCP                     │
│ Oferece análises como tools     │
│ "execute_vendas_por_regiao"     │
│ "execute_anomalias_vendas"      │
└─────────────────────────────────┘
```

**Timing:** 1-2 segundos (cold), < 100ms (cache warm)

---

### 3.2 Fluxo: Execução de Análise

```
┌──────────────────────────┐
│   Cliente MCP            │
│  Chama: execute_analysis │
│  (id="vendas_por_regiao",│
│   params={mes: "2026-09"})
└─────────┬────────────────┘
          │
┌─────────▼──────────────────────────────────┐
│  FastAPI MCP Server                        │
│  call_tool(name, arguments)                │
│  ├─ 1. Parse arguments                    │
│  ├─ 2. CacheService.get_or_execute()      │
│  │    ├─ Cache hit? Retorna cached       │
│  │    ├─ Cache miss → continua            │
│  │    └─ Check TTL                        │
│  ├─ 3. AnalysisService.execute()         │
│  │    ├─ Load analysis definition        │
│  │    ├─ Get DataSource config           │
│  │    ├─ Select Adapter                  │
│  │    ├─ VolumeGuardService.check_row_count()          │
│  │    │    ├─ Adapter.execute_query(SELECT COUNT(*))  │
│  │    │    └─ Excede limite? → devolve volume_exceeded, PARA aqui │
│  │    ├─ STEP 1 (query)                  │
│  │    │    ├─ Adapter.connect()          │
│  │    │    ├─ Adapter.execute_query()    │
│  │    │    └─ Result: dataset bruto      │
│  │    └─ VolumeGuardService.check_serialized_size()    │
│  │         └─ Excede KB? → devolve volume_exceeded (mesmo com count ok) │
│  ├─ 4. AuditService.log_execution()      │
│  ├─ 5. CacheService.set(result, ttl)    │
│  └─ 6. Return JSON result (dataset bruto)│
└─────────┬──────────────────────────────────┘
          │
┌─────────▼────────────────────────┐
│   Cliente MCP                    │
│   Recebe resultado               │
│   {status: "success", data: [...]}│
│   Mostra para o usuário          │
└──────────────────────────────────┘
```

**Timing Total:**
- Leve (< 1s query): 2-5s
- Média (1-5s query): 5-15s
- Pesada (> 5s): async (remoto)

---

### 3.3 Fluxo: Versionamento

```
┌──────────────────┐
│  Jose insere SQL │
│  em analysis_steps│
└────────┬─────────┘
         │
┌────────▼───────────────────────────┐
│  VersionService.create_version()   │
│  ├─ 1. Load análise atual (v1)    │
│  ├─ 2. Load nova definição        │
│  ├─ 3. Compare (diff)             │
│  ├─ 4. Create análise_versions    │
│  │    ├─ version_number = 2       │
│  │    ├─ full_definition = snapshot│
│  │    └─ changes_summary = diff    │
│  ├─ 5. Update analyses table      │
│  │    └─ version_id = v2          │
│  └─ 6. Log no histórico           │
└────────┬───────────────────────────┘
         │
┌────────▼──────────────────────┐
│  Análise agora em v2          │
│  V1 permanece acessível       │
│  Histórico completo           │
└───────────────────────────────┘

Rollback (se necessário):
┌──────────────────┐
│  Jose clica      │
│  "Rollback v1"   │
└────────┬─────────┘
         │
┌────────▼──────────────────────────┐
│ VersionService.rollback()         │
│ ├─ Load v1 definition            │
│ ├─ Restore analysis steps        │
│ ├─ Update version_id = v1        │
│ └─ Log: "Rollback por Jose"      │
└────────┬──────────────────────────┘
         │
┌────────▼────────────────────┐
│ Análise restaurada para v1  │
│ V2 continua no histórico    │
└─────────────────────────────┘
```

---

### 3.4 Fluxo: Controle de Volume de Dados

Como o servidor não transforma mais os dados (§1, §2.1), o dataset bruto vai
inteiro para o cliente MCP — e um resultado de milhares de linhas pode custar
centenas de milhares de tokens. Esta camada evita isso, em duas etapas:

```
1. Cliente MCP chama execute_analysis(id, params)
2. VolumeGuardService roda um SELECT COUNT(*) barato, com os mesmos filtros
   da query real, ANTES de buscar qualquer dado
   ├─ count > DEFAULT_MAX_RESULT_ROWS → RECUSA (passo 5), nunca busca os dados completos
   └─ count <= DEFAULT_MAX_RESULT_ROWS → segue para o passo 3
3. AnalysisService executa a query completa (STEP 1) e serializa o resultado em JSON
   └─ VolumeGuardService confere o tamanho real em KB — segunda checagem de segurança
      (o count de linhas pode não refletir o tamanho real se as colunas forem muito largas)
4. Se dentro dos dois limites: devolve o dataset bruto normalmente
5. Se qualquer checagem falhar (linhas OU KB) e confirmar_volume_alto=false (default):
   devolve uma resposta estruturada "volume_exceeded" (ver exemplo abaixo),
   sem nunca ter buscado o dataset completo (a menos que a falha tenha sido a de KB,
   caso em que os dados já foram buscados só para medir — ver nota abaixo)
```

> Nota: como a checagem de KB só é possível depois de serializar o resultado, o caso
> "count baixo mas colunas muito largas" busca o dado uma vez para medir e ainda assim
> recusa devolvê-lo ao cliente. É um custo aceito (query já filtrada pelo `COUNT(*)`
> anterior, então o volume de linhas já é baixo) em troca de nunca devolver ao cliente
> um payload maior que o limite configurado.

**Parâmetro reservado `confirmar_volume_alto`** — injetado pelo servidor no JSON Schema
de toda tool MCP (não cadastrado em `analyses.parameters`, é global):
```json
{
  "confirmar_volume_alto": {
    "type": "boolean",
    "required": false,
    "default": false,
    "description": "Confirma execução mesmo que o resultado seja grande (maior consumo de tokens)"
  }
}
```

**Resposta de recusa** (`confirmar_volume_alto=false`, volume acima do limite):
```json
{
  "status": "volume_exceeded",
  "estimativa": { "linhas": 8400, "tamanho_estimado_kb": 510 },
  "limite": { "linhas": 500, "tamanho_kb": 150 },
  "mensagem": "Sua consulta retornaria aproximadamente 8.400 linhas (~510KB), acima do limite de 500 linhas / 150KB. Refine o período ou adicione filtros (ex: região, produto). Se quiser continuar mesmo assim, chame novamente com confirmar_volume_alto=true — atenção: isso pode consumir um volume alto de tokens."
}
```

Se o cliente chamar de novo com `confirmar_volume_alto=true`, o servidor **ignora o
limite** e devolve o dataset completo, incluindo `"aviso": "resultado grande, enviado
por confirmação explícita"` no payload.

**Configuração — 100% via `.env`, sem override por análise:**
```
# .env
DEFAULT_MAX_RESULT_ROWS=500
DEFAULT_MAX_RESULT_SIZE_KB=150
```

Ambos os limites são globais; não há coluna nova em `analyses` para isso, e nenhuma
migration de schema é necessária além da remoção de `custom_handlers` (§2.2).

---

## 4. Padrões de Design

### 4.1 Repository Pattern

```python
# Abstração de acesso a dados
class AnalysisRepository:
    async def get_by_id(self, analysis_id: UUID) -> Analysis
    async def get_all(self) -> List[Analysis]
    async def create(self, analysis: AnalysisCreate) -> Analysis
    async def update(self, analysis_id: UUID, data: dict) -> Analysis
    async def delete(self, analysis_id: UUID) -> None

# Implementação
class PostgreSQLAnalysisRepository(AnalysisRepository):
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def get_by_id(self, analysis_id: UUID) -> Analysis:
        result = await self.db.query(
            "SELECT * FROM analyses WHERE id = $1",
            analysis_id
        )
        return Analysis(**result)
```

### 4.2 Factory Pattern (Adapters)

```python
class AdapterFactory:
    _adapters = {
        'postgresql': PostgreSQLAdapter,
        'mongodb': MongoDBAdapter,
        'mysql': MySQLAdapter,
        'sqlserver': SQLServerAdapter,
        'api': APIAdapter
    }

    @classmethod
    def create_adapter(cls, source_type: str, config: dict):
        AdapterClass = cls._adapters.get(source_type)
        if not AdapterClass:
            raise ValueError(f"Adapter '{source_type}' não encontrado")
        return AdapterClass(config)

# Uso
adapter = AdapterFactory.create_adapter('postgresql', config)
data = await adapter.execute_query(sql)
```

### 4.3 Volume Guard (Controle de Volume)

Não é um Registry nem depende de discovery de filesystem/banco — é um serviço leve,
usado diretamente pelo `AnalysisService` dentro do fluxo de execução (ver §3.4):

```python
class VolumeGuardService:
    def __init__(self, max_rows: int, max_size_kb: int):
        self.max_rows = max_rows          # DEFAULT_MAX_RESULT_ROWS (.env)
        self.max_size_kb = max_size_kb    # DEFAULT_MAX_RESULT_SIZE_KB (.env)

    async def check_row_count(self, adapter, count_sql: str, params: dict) -> int:
        count = await adapter.execute_query(count_sql, params, scalar=True)
        if count > self.max_rows:
            raise VolumeExceededError(estimated_rows=count)
        return count

    def check_serialized_size(self, result: list[dict]) -> int:
        size_kb = len(json.dumps(result).encode("utf-8")) / 1024
        if size_kb > self.max_size_kb:
            raise VolumeExceededError(estimated_size_kb=size_kb)
        return size_kb

    def build_refinement_response(self, error: VolumeExceededError) -> dict:
        return {
            "status": "volume_exceeded",
            "estimativa": {"linhas": error.estimated_rows, "tamanho_estimado_kb": error.estimated_size_kb},
            "limite": {"linhas": self.max_rows, "tamanho_kb": self.max_size_kb},
            "mensagem": "...",  # ver §3.4 para o texto completo
        }
```

### 4.4 Strategy Pattern (Execution)

```python
class ExecutionStrategy(ABC):
    @abstractmethod
    async def execute(self, analysis_id, params):
        pass

class InProcessExecutor(ExecutionStrategy):
    async def execute(self, analysis_id, params):
        return await analysis_service._execute_in_process(analysis_id, params)

class AsyncExecutor(ExecutionStrategy):
    async def execute(self, analysis_id, params):
        task = execute_analysis_task.delay(analysis_id, params)
        return {"status": "queued", "task_id": str(task.id)}

executor = InProcessExecutor() if is_light else AsyncExecutor()
result = await executor.execute(analysis_id, params)
```

---

## 5. Stack Técnico

### 5.1 Dependências Principais

```
# requirements.txt

# Web Framework
# Sem versão exata fixada de propósito: no protótipo F0, fixar fastapi==0.104.1 +
# uvicorn[standard]==0.24.0 junto de mcp>=1.2.0 gerou ResolutionImpossible (dependências
# transitivas do mcp exigem fastapi/starlette mais recentes). Deixar o pip resolver a
# versão compatível e travar só o `mcp` (abaixo) evita esse conflito.
fastapi
uvicorn[standard]
pydantic
pydantic-settings

# MCP
mcp>=1.9.0,<2.0.0  # teto obrigatório: a v2.0.0 remove os decorators list_tools()/call_tool()
                    # da classe de baixo nível Server usada no ADR-006 (confirmado no protótipo F0,
                    # que fixou mcp==1.30.0 — última 1.x com essa API)

# Database
asyncpg==0.29.0  # PostgreSQL async driver
motor==3.3.2     # MongoDB async driver
aiomysql==0.2.0  # MySQL async driver
aioodbc==0.4.0   # SQL Server async driver (via ODBC)
pyodbc==5.0.1    # Driver ODBC nativo, dependência do aioodbc para SQL Server
sqlalchemy==2.0.23
alembic==1.13.0

# Data Processing
pandas==2.1.3
numpy==1.26.2

# Async & Caching
redis==5.0.1
aioredis==2.0.1

# Task Queue (Remoto)
celery==5.3.4

# Data Validation
marshmallow==3.20.1

# Logging & Monitoring
python-json-logger==2.0.7
structlog==23.2.0

# Security
cryptography==41.0.7  # Fernet — cifra connection_config.password em repouso (ver §8.2)

# Utils
python-dotenv==1.0.0
uuid6==1.0.3
```

> ⚠️ **Dependência de SO para SQL Server:** `pyodbc`/`aioodbc` precisam do driver ODBC nativo instalado no sistema (não é só `pip install`) — no Linux/Docker, isso significa instalar o pacote `msodbcsql17` (ou `18`) da Microsoft via `apt` antes de instalar os pacotes Python. Isso entra no `Dockerfile` na F14 (Docker Setup) e é um pré-requisito manual se rodar fora de container.

### 5.2 Python Structure

```
analysis_app/
├── main.py                    # FastAPI app entry point (Streamable HTTP)
├── config.py                  # Configuration (pydantic)
├── requirements.txt
├── docker-compose.local.yml
├── docker-compose.remote.yml
│
├── adapters/
│   ├── __init__.py
│   ├── base.py               # DatabaseAdapter (abstract)
│   ├── postgresql.py
│   ├── mongodb.py
│   ├── mysql.py
│   ├── sqlserver.py          # via aioodbc/pyodbc — requer driver ODBC do SO (ver nota abaixo)
│   └── api_adapter.py
│
├── services/
│   ├── __init__.py
│   ├── analysis_service.py   # Core execution logic
│   ├── volume_guard_service.py  # Pré-checagem de linhas/KB (ver §3.4, §4.3)
│   ├── cache_service.py      # Caching logic
│   ├── version_service.py    # Versioning & rollback
│   └── audit_service.py      # Logging (simplificado)
│
├── repositories/
│   ├── __init__.py
│   ├── base.py
│   ├── analysis_repo.py
│   ├── data_source_repo.py
│   ├── version_repo.py
│   └── execution_repo.py
│
├── schemas/
│   ├── __init__.py
│   ├── analysis.py           # Pydantic models
│   ├── data_source.py
│   ├── execution.py
│   └── analysis_parameters.py  # to_json_schema() / to_pydantic_model() — ver proposta §5
│
├── mcp_transport/             # nome definitivo — "mcp/" colide com o SDK `mcp` importado
│   │                          # dentro do próprio pacote (confirmado na implementação de F1)
│   ├── __init__.py
│   ├── resources.py          # MCP resources (list_resources, read_resource)
│   └── tools.py              # MCP tools (list_tools, call_tool)
│
├── database/
│   ├── __init__.py
│   ├── connection.py         # DB connection pool
│   ├── migrations/
│   │   ├── versions/         # Alembic migrations
│   │   └── env.py
│   └── models.py             # SQLAlchemy models
│
├── logs/
│   ├── app.log
│   └── audit.log
│
└── tests/
    ├── __init__.py
    ├── test_analysis_service.py
    ├── test_volume_guard_service.py
    ├── test_cache_service.py
    └── fixtures.py
```

---

## 6. Fluxo de Inicialização

### 6.1 Startup (Startup Event)

```
FastAPI Startup (processo uvicorn persistente):
├─ 1. Load config (.env)
│    └─ Inclui DEFAULT_MAX_RESULT_ROWS, DEFAULT_MAX_RESULT_SIZE_KB (VolumeGuardService)
├─ 2. Connect to PostgreSQL (config DB)
├─ 3. Setup connection pools
│    └─ PostgreSQL, MongoDB, Redis (se ativado)
├─ 4. Initialize CacheService
│    └─ Decide: memory (local) ou Redis (remoto)
├─ 5. Verify all data_sources are reachable
└─ 6. Register MCP endpoints via Streamable HTTP
    ├─ list_tools()
    ├─ call_tool()
    ├─ list_resources()
    └─ read_resource()

Total time: 3-5 segundos
```

### 6.2 Shutdown

```
FastAPI Shutdown:
├─ 1. Close all DB connections
├─ 2. Flush cache to disk (se remoto)
├─ 3. Log final entries no histórico de execução
└─ 4. Clean up temp files

Total time: < 1 segundo
```

---

## 7. Decisões Arquiteturais (ADRs)

### ADR-001: FastAPI + MCP (não Flask, não Django)

**Decisão:** Usar FastAPI com MCP SDK
**Razão:**
- ✅ Async/await nativo (melhor para I/O de BD)
- ✅ MCP SDK é otimizado para FastAPI
- ✅ Pydantic built-in (validação tipada)
- ✅ Documentação automática (Swagger)

**Alternativas Rejeitadas:**
- ❌ Django: muito pesado para MCP
- ❌ Aiohttp puro: menos abstrações, mais verboso

---

### ADR-002: Cache Adaptativo (memória local, Redis remoto)

**Decisão:** Não forçar Redis localmente
**Razão:**
- ✅ PostgreSQL em localhost = < 1ms latência
- ✅ Cache em memória é suficiente
- ✅ Zero overhead de rede local
- ✅ Remoto: upgrade para Redis sem mudança de código

---

### ADR-003: Executores Híbridos (in-process + Celery)

**Decisão:** In-process para leves, Celery para pesados (remoto)
**Razão:**
- ✅ Local: zero overhead, resposta rápida
- ✅ Remoto: escalabilidade horizontal
- ✅ Mesmo código em ambos ambientes

---

### ADR-004: PostgreSQL como Config DB

**Decisão:** PostgreSQL dedicado para configurações
**Razão:**
- ✅ Separação: config vs dados de negócio
- ✅ ACID transactions para versionamento
- ✅ Fácil backup e restore
- ✅ Suporta JSONB para flexibilidade

---

### ADR-005: Servidor Entrega Dataset Bruto — Sem Camada de Handlers

**Decisão:** O servidor não transforma mais os dados. Ele executa a query parametrizada
de `analysis_steps` e devolve o resultado bruto (JSON) ao cliente MCP; é o LLM do lado
do cliente quem interpreta, calcula, agrega e visualiza os dados, a cada pedido.
**Razão:**
- ✅ O espaço de perguntas de análise que um usuário pode fazer é infinito ("tendência
  de vendas", "sazonalidade", "correlação entre X e Y") — não é viável pré-programar
  um handler Python para cada tipo de análise possível
- ✅ Qualquer LLM moderno já sabe interpretar, agregar e até gerar gráfico a partir de
  um dataset bruto — reimplementar isso em Python no servidor é trabalho duplicado
- ✅ Reduz drasticamente a superfície de código do servidor (sem Registry, sem discovery
  de filesystem/banco, sem classes de handler para manter)
- ⚠️ Risco introduzido: datasets grandes podem estourar o contexto/custo de tokens do
  cliente — mitigado pelo **Volume Guard** (§3.4, §4.3), que recusa e pede refinamento
  antes de buscar dados demais

**Alternativas Rejeitadas:**
- ❌ Manter Handlers Python (`HandlerRegistry`, discovery built-in + custom): não escala
  para o espaço aberto de análises que os usuários pedem; cada handler novo exigia
  código Python, indo contra o objetivo de "zero código novo por análise" (NEGOCIO.md O1)
- ❌ Handlers "genéricos" configuráveis via JSON (ex.: um handler de agregação
  parametrizável): ainda limitado às operações pré-pensadas; o LLM cliente já faz isso
  sem limite de operações suportadas

**Substitui:** o antigo ADR-005 ("Handlers como Python Classes"), a tabela `custom_handlers`
(removida do schema, §2.2) e o antigo F3 do roadmap ("HandlerRegistry e Discovery"),
agora "Controle de Volume de Resultado" — ver FEATURES_ROADMAP.md v1.6.

---

### ADR-006: MCP via Streamable HTTP com TLS, Agnóstico de Cliente, Sem Autenticação em V1.0

**Decisão:** Servidor MCP roda como serviço Streamable HTTP persistente na rede interna, com TLS (HTTPS), aceitando qualquer cliente MCP padrão, sem autenticação.
**Razão:**
- ✅ Funciona com qualquer cliente MCP (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.) simultaneamente
- ✅ Não fica preso a um único cliente
- ✅ Rede interna é assumida confiável, então autenticação não é necessária em V1.0
- ✅ Simplifica drasticamente o desenvolvimento inicial
- ✅ TLS é obrigatório **mesmo assim** — não por política de segurança da arquitetura, mas porque clientes MCP reais recusam se conectar a um conector remoto via `http://` simples (confirmado empiricamente no protótipo F0 com Claude Desktop: a conexão TLS era abandonada antes mesmo de chegar uma requisição HTTP ao servidor)

**Alternativas Rejeitadas:**
- ❌ stdio (subprocesso por usuário): não permite múltiplos clientes/usuários na mesma instância compartilhada
- ❌ HTTP+SSE (endpoint `/sse`): transporte usado nas versões 1.0-1.3 deste ADR; substituído por ser a versão anterior/legada do protocolo MCP para transporte remoto — Streamable HTTP é o transporte atual recomendado pela especificação, com endpoint único (`/mcp`) e mesmo modelo de sessão
- ❌ HTTP simples (sem TLS): tecnicamente mais simples e "suficiente" para uma rede interna confiável, mas rejeitado porque, na prática, clientes MCP desktop recusam conectores remotos sem HTTPS — não é uma opção viável mesmo em V1.0
- ❌ Proprietário: dificulta integração com novos clientes
- ❌ Autenticação desde já: complexidade desnecessária para rede confiável (fica para quando o requisito de exposição remota existir — ver §12)

**Consequências práticas confirmadas no protótipo F0 (ver `F0_PROTOTIPO_MCP_MEMORIA.md`):**
- Certificado TLS é dependência obrigatória mesmo em desenvolvimento local — mkcert para gerar um certificado confiável localmente (máquina única); CA interna instalada em cada máquina cliente quando o servidor precisar ser acessado por mais de uma máquina na rede.
- A CLI padrão do uvicorn (`--ssl-certfile`/`--ssl-keyfile`) **não negocia ALPN** — alguns clientes (Chromium/Electron) abandonam a conexão TLS sem nunca enviar uma requisição HTTP se o servidor não participar da negociação ALPN. É necessário configurar um `ssl_context_factory` programático que chame `context.set_alpn_protocols(["http/1.1"])`.
- O endpoint `/mcp`, se montado via `app.mount("/mcp", ...)` do Starlette/FastAPI, responde com redirect `307` para `/mcp/` quando a requisição bate exatamente em `/mcp` sem barra final — o padrão de URL usado por clientes reais. É necessário registrar também uma rota exata (`app.add_route("/mcp", ...)`) para esse caso, evitando o redirect. O próprio `FastMCP` (wrapper de alto nível do SDK, não usado aqui) resolve isso da mesma forma — registrando uma `Route` exata em vez de um `Mount`.
- CORS precisa ser habilitado mesmo sem um navegador tradicional envolvido — clientes desktop (Electron) podem validar o conector via `fetch()` no processo de renderer, sujeito à mesma política de CORS de um browser.

**Substitui:** os antigos ADR-007 (Client Identification Automática) e ADR-008 (Autenticação Multi-User via API Key), removidos junto com o serviço correspondente, e revisa a própria decisão de transporte deste ADR-006 (v1.0-1.3: HTTP+SSE → v1.4: Streamable HTTP → v1.5: Streamable HTTP com TLS obrigatório). A especificação técnica dos ADRs de identificação é preservada como referência para reintrodução futura.

---

## 8. Considerações de Segurança

### 8.1 Rede Interna, Sem Autenticação (V1.0)

```
✅ Implementar em V1.0:
├─ SQL Injection prevention
│  └─ Parametrized queries ALWAYS
├─ Input validation
│  └─ Pydantic schemas em tudo
├─ Timeout protection
│  └─ Max 60s por query (remoto) / 30s (local)
└─ Log de execução
   ├─ O quê (qual análise) foi executado
   ├─ Quando (timestamp)
   └─ Resultado (success/fail)

❌ Não implementar em V1.0 (rede privada confiável):
├─ Autenticação/identificação de usuário ou cliente MCP
├─ Rate limiting / quotas por usuário
├─ TLS/SSL entre cliente-servidor (confiança local)
├─ CORS (não é cross-origin, todos locais)
├─ RBAC avançado (roles complexos)
└─ SSO/LDAP (complexo para rede local)

⚠️ Futuro (quando expor remotamente ou sair da rede confiável — V1.1+):
├─ Reintroduzir ClientIdentificationService (qual cliente MCP)
├─ Reintroduzir UserIdentificationService (qual pessoa, API Key, quota)
├─ SSL/TLS entre cliente → servidor
├─ Rate limiting mais rigoroso
├─ IP whitelist
├─ SSO/LDAP/Azure AD
└─ RBAC granular (quem pode executar qual análise)
```

### 8.2 Credenciais de BD

```
✅ Armazenar:
├─ connection_config em JSONB (campo `password` e demais credenciais cifrados
│  com Fernet — biblioteca `cryptography` do Python — antes de persistir)
├─ Usar .env para secrets (Docker)
└─ Log de execução como trilha de acesso

Exemplo .env:
POSTGRES_CONFIG_PASSWORD=secure_password
MONGODB_CONNECTION_STRING=mongodb+srv://...
FERNET_KEY=<chave gerada com Fernet.generate_key(), fora do repositório>
```

**Formato de `data_sources.connection_config`** (ver §2.2, Tabela 1 — antes um placeholder):
```json
{
  "host": "192.168.1.10",
  "port": 5432,
  "database": "vendas_db",
  "user": "readonly_user",
  "password": "<cifrado com Fernet>",
  "sslmode": "prefer"
}
```

---

## 9. Plano de Implantação

### 9.1 Local (Desenvolvimento)

```bash
# Preparar
git clone <repo>
cd analysis_app
cp .env.example .env

# Certificado TLS local (obrigatório — ver ADR-006):
brew install mkcert && mkcert -install
mkcert -cert-file certs/server.pem -key-file certs/server-key.pem localhost 127.0.0.1 <ip-da-maquina>

# Docker compose local
docker-compose -f docker-compose.local.yml up

# Verificar
curl https://localhost:3000/health

# Configuração em cada cliente MCP (exemplo genérico, formato varia por app):
# {
#   "mcpServers": {
#     "analysis": { "url": "https://<ip-da-maquina>:3000/mcp" }
#   }
# }
#
# Repita a mesma URL em Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.
# Não é necessário nenhum header ou API Key em V1.0 — mas HTTPS é obrigatório
# (ver ADR-006): clientes MCP reais recusam conector remoto via http:// simples,
# mesmo em rede interna confiável. Se o cliente estiver em outra máquina, instale
# a CA do mkcert (`mkcert -CAROOT`) nela antes de confiar no certificado.
#
# ⚠️ Subir o servidor apenas com `uvicorn --ssl-certfile=... --ssl-keyfile=...`
# não basta: a CLI do uvicorn não negocia ALPN, e alguns clientes (Chromium/Electron)
# abandonam a conexão TLS sem nunca enviar uma requisição HTTP. É necessário um
# `ssl_context_factory` programático chamando `context.set_alpn_protocols(["http/1.1"])`
# (ver protótipo F0, `run_https.py`).
```

**Tempo de setup:** 5-10 minutos

### 9.2 Produção Interna (nginx + Certbot)

Ainda dentro de V1.0 — rede interna, sem exposição pública (Restrição T1) — mas num servidor dedicado em vez da máquina de desenvolvimento. Aqui, **nginx** faz a terminação TLS como reverse proxy na frente do FastAPI/uvicorn, que passa a rodar atrás dele em HTTP simples. Isso elimina a necessidade do `ssl_context_factory`/ALPN manual da seção 9.1: o OpenSSL do nginx já negocia ALPN nativamente, então esse workaround é específico do cenário "uvicorn falando TLS diretamente" (dev com mkcert), não de produção com nginx.

```nginx
# /etc/nginx/sites-available/analysis-mcp
server {
    listen 443 ssl;
    server_name analise.empresa.internal;

    ssl_certificate     /etc/letsencrypt/live/analise.empresa.internal/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/analise.empresa.internal/privkey.pem;

    location /mcp {
        proxy_pass http://127.0.0.1:3000/mcp;
        proxy_http_version 1.1;
        proxy_set_header Connection "";   # necessário para o streaming (SSE) do Streamable HTTP
        proxy_buffering off;
        proxy_set_header Host $host;
    }

    location /health {
        proxy_pass http://127.0.0.1:3000/health;
    }
}
```

**Certificado via Certbot — duas opções, a escolher quando o servidor de produção for provisionado:**

**Opção A — DNS-01 com domínio público (se a operação já tiver domínio + acesso à API do provedor de DNS):**
```bash
certbot certonly --dns-<provedor> \
  --dns-<provedor>-credentials /etc/letsencrypt/<provedor>.ini \
  -d analise.empresa.internal
# renovação automática via cron/systemd timer do próprio certbot
```
Não exige expor o servidor à internet — o desafio DNS-01 só cria um registro TXT no DNS **público** do domínio; o hostname em si pode continuar resolvendo só internamente (DNS split-horizon).

> **Confiança do cliente: nenhuma configuração extra.** O certificado é assinado pela CA do Let's Encrypt, que já vem pré-instalada por padrão em todo sistema operacional, navegador e runtime (macOS, Windows, Linux, Node.js, etc.) — exatamente como qualquer certificado de uma API pública comum. Nenhum cliente MCP precisa instalar ou confiar em nada; a URL `https://analise.empresa.internal:3000/mcp` funciona de imediato, do mesmo jeito que funcionaria acessando qualquer site HTTPS público.

**Opção B — CA interna própria (sem depender de domínio público):**
```bash
certbot certonly --server https://sua-ca-interna.empresa.internal/acme/directory \
  -d analise.empresa.internal
```
Certbot suporta qualquer servidor compatível com ACME via `--server`, não só o Let's Encrypt — uma CA interna (ex.: `step-ca`) resolve isso sem tocar em DNS público.

> **Confiança do cliente: mesma exigência do mkcert (seção 9.1).** Essa CA interna é privada — não está pré-instalada em lugar nenhum, então nenhum cliente confia nela por padrão. É necessário instalar/confiar nessa CA em cada máquina cliente antes de conseguir se conectar via HTTPS (import do certificado raiz no Keychain/Certificate Store/`ca-certificates`, conforme o SO). A vantagem sobre o mkcert é só a renovação centralizada e automática pelo Certbot, em vez de manual por máquina — mas o ônus de confiança client-side é o mesmo.

> **Resumindo a diferença entre as opções:** o que exige (ou não) tocar em cada cliente não é "nginx+Certbot vs. mkcert" — é se o certificado é assinado por uma CA pública já confiável de fábrica (Opção A) ou por uma CA privada que só existe porque você a criou (Opção B e mkcert). Nenhuma das duas opções muda o resto da arquitetura: o app continua servindo em `/mcp` sem autenticação, conforme ADR-006 — só a origem/renovação do certificado, e a necessidade (ou não) de configurar os clientes, mudam.

### 9.3 Remoto (Produção — Futuro)

```bash
docker build -t analysis-mcp:1.0 .
docker tag analysis-mcp:1.0 registry.company.com/analysis-mcp:1.0
docker push registry.company.com/analysis-mcp:1.0

kubectl create namespace analysis
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

kubectl get pods -n analysis
kubectl logs -n analysis <pod-name>
```

> ⚠️ Antes deste passo, reintroduzir autenticação (ver §7 ADR-006 e §12).

---

## 10. Monitoramento e Observabilidade

### 10.1 Métricas

```python
from prometheus_client import Counter, Histogram

analysis_executions = Counter(
    'analysis_executions_total',
    'Total de execuções',
    ['analysis_id', 'status']
)

execution_duration = Histogram(
    'analysis_execution_seconds',
    'Duração da execução',
    ['analysis_id']
)

cache_hits = Counter(
    'cache_hits_total',
    'Hits no cache',
    ['analysis_id']
)
```

### 10.2 Logging

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "analysis_executed",
    analysis_id=str(analysis_id),
    version=version_id,
    status="success",
    execution_time_ms=1234,
    cached=False
)
```

### 10.3 Health Check

```python
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "db": await check_postgres(),
        "cache": await check_cache(),
        "volume_limits": {"max_rows": settings.DEFAULT_MAX_RESULT_ROWS, "max_size_kb": settings.DEFAULT_MAX_RESULT_SIZE_KB},
        "analyses": await AnalysisService.count()
    }
```

---

## 11. Diagrama de Sequência (Caso de Uso Principal)

```
Cliente MCP       FastAPI Server    PostgreSQL              Cache
    │                 │                 │                      │
    │ list_tools()   │                 │                      │
    ├────────────────>│                 │                      │
    │                 │ SELECT analyses │                      │
    │                 ├────────────────>│                      │
    │                 │<────────────────┤                      │
    │<────────────────┤ [análise_1, análise_2, ...]            │
    │                 │                 │                      │
    │ execute_analysis│                 │                      │
    ├────────────────>│                 │                      │
    │                 │ get_or_execute  │                      │
    │                 ├─────────────────────────────────────────>│
    │                 │<─────────────────────────────────────────┤ cache miss
    │                 │ SELECT steps    │                      │
    │                 ├────────────────>│                      │
    │                 │<────────────────┤                      │
    │                 │ SELECT COUNT(*) (Volume Guard pré-check)│
    │                 ├────────────────>│                      │
    │                 │<────────────────┤ excede limite? recusa aqui
    │                 │ execute query (dataset bruto)          │
    │                 ├────────────────>│                      │
    │                 │<────────────────┤                      │
    │                 │ set cache       │                      │
    │                 ├─────────────────────────────────────────>│
    │                 │ log execution   │                      │
    │                 ├────────────────>│                      │
    │<────────────────┤ result (JSON, dataset bruto)            │
    │                 │                 │                      │
```

---

## 12. Roadmap Arquitetural

```
V1.0 (MVP Local):
├─ MCP via Streamable HTTP, sem autenticação
├─ Multi-cliente simultâneo (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.)
└─ Log de execução básico (sem identificação de usuário/cliente)

V1.1 (Reintrodução de Identificação — quando necessário):
├─ ClientIdentificationService: qual cliente MCP executou
├─ UserIdentificationService: qual pessoa executou (API Key + quota)
├─ Necessário antes de expor além da rede confiável
└─ Especificação técnica detalhada já existe e pode ser retomada

V1.2 (Production Remoto):
├─ Redundância e failover
├─ Load balancing
├─ Kubernetes deployment
└─ Dashboard de uso

V2.0 (Ecosystem):
├─ Qualquer cliente MCP (aberto)
├─ Marketplace compartilhado
├─ Multi-tenant (múltiplas orgs)
└─ MCP como padrão de facto
```

---

## 13. Decisão de Tecnologias

| Componente | Tecnologia | Justificativa |
|-----------|-----------|---------------|
| **Web Framework** | FastAPI | Async nativo, MCP SDK support, Streamable HTTP |
| **Config DB** | PostgreSQL | JSONB, ACID, versionamento |
| **Data Sources** | PostgreSQL, MySQL, SQL Server, MongoDB, API | Adaptadores agnósticos |
| **Cache (Local)** | Memória + Dict | Zero overhead, suficiente |
| **Cache (Remoto)** | Redis | Distributed, cluster-ready |
| **Task Queue** | Celery | Escala horizontal, remoto |
| **Controle de Volume** | VolumeGuardService (COUNT(*) + checagem de KB) | Evita estourar tokens do cliente, sem handler nenhum |
| **Containerização** | Docker | Portabilidade local ↔ remoto |
| **Orchestração** | Docker Compose (local), Kubernetes (remoto) | Simplicity + power |

---

## 14. Prototipagem e Proof of Concept

### Sprint 0 (Protótipo — 1 semana)

```
├─ FastAPI hello world (Streamable HTTP)
├─ 1 PostgreSQL adapter
├─ VolumeGuardService básico (checagem de linhas)
├─ 1 análise de exemplo
├─ MCP list_tools() + call_tool()
├─ 2 clientes MCP diferentes conectados simultaneamente
└─ Análise executando e retornando dados para ambos
```

**Sucesso:** pedir "Mostre vendas de setembro" em dois clientes MCP diferentes (ex.: Claude Desktop e Gemini Desktop), ao mesmo tempo, e receber dados reais do BD local em ambos.

---

**Documento de Arquitetura Completo.**
**Pronto para começar desenvolvimento.**
