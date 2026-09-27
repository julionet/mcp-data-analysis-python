# 🗄️ Esquema do Banco de Dados

## Plataforma de Análise de Dados Genérica com MCP

**Referência:** ARQUITETURA.md §2.2 e §2.3 (v1.12)
**Banco:** `analysis_config` (PostgreSQL local — config DB, separado dos data sources de negócio)
**Data:** 2026-09-27

> Este documento descreve apenas o **banco de configuração** da própria plataforma (onde ficam análises, versões, histórico etc.). Os bancos de negócio conectados como `data_sources` (PostgreSQL/MySQL/SQL Server/MongoDB dos clientes) não têm schema fixo — são externos e arbitrários.

---

## 1. Diagrama de Relacionamento (Visão Geral)

```
data_sources (1) ──────< (N) analyses
                              │
                              ├──────< (N) analysis_steps
                              │
                              ├──────< (N) analysis_versions
                              │                │
                              │                │ (opcional)
                              └──────< (N) execution_history >──── (0..1) analysis_versions
```

- Uma **análise** pertence a exatamente uma **fonte de dados** (`data_sources`).
- Uma **análise** tem N **etapas** (`analysis_steps`) — em V1.0, sempre uma etapa do tipo `query`.
- Uma **análise** acumula N **versões** (`analysis_versions`) ao longo do tempo.
- Cada **execução** (`execution_history`) referencia a análise executada e, opcionalmente, qual versão específica foi usada.

---

## 2. Tabelas

### 2.1 `data_sources` — Fontes de Dados

Representa uma conexão a um banco de dados externo (o "de onde" os dados de negócio vêm).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único, gerado automaticamente |
| `name` | VARCHAR(255) | ✅ (UNIQUE) | Nome único da fonte de dados (ex.: `"vendas_db"`) |
| `type` | VARCHAR(50) | ✅ | Tipo do banco: `postgresql`, `mysql`, `sqlserver`, `mongodb`, `api` |
| `connection_config` | JSONB | ✅ | `{host, port, database, user, password (cifrado com Fernet), sslmode}` — ver §3 |
| `is_active` | BOOLEAN | — | Default `true`. Fontes inativas não podem ser usadas em novas análises |
| `created_by` | VARCHAR(255) | — | Quem criou o registro |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` |

**Relacionamentos:** referenciada por `analyses.data_source_id` (1 fonte → N análises).

---

### 2.2 `analyses` — Análises (Definições)

A definição de "o que" uma análise faz — nome, descrição, de onde vêm os dados e quais parâmetros aceita. Não guarda o SQL diretamente (isso fica em `analysis_steps`).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `name` | VARCHAR(255) | ✅ (UNIQUE) | Nome único da análise (ex.: `"vendas_por_regiao"`) — é o nome exposto como tool MCP |
| `description` | TEXT | — | Descrição usada pelo LLM cliente para entender o que a análise faz |
| `data_source_id` | UUID (FK → `data_sources.id`) | — | Qual fonte de dados essa análise consulta |
| `cache_frequency` | VARCHAR(50) | — | Default `'daily'`. Controla o TTL do cache (F7) — `'none'` desativa cache |
| `parameters` | JSONB | — | Schema dos parâmetros aceitos (ver §3) — convertido para JSON Schema MCP |
| `is_active` | BOOLEAN | — | Default `true` |
| `created_by` | VARCHAR(255) | — | Quem criou/configurou a análise |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` — usado como parte da chave de cache (F7) |

**Relacionamentos:**
- N:1 com `data_sources` (uma análise pertence a uma fonte)
- 1:N com `analysis_steps`, `analysis_versions`, `execution_history`

---

### 2.3 `analysis_steps` — Etapas da Análise

O SQL efetivo que a análise executa. Em V1.0, toda análise tem exatamente 1 step do tipo `query` (a coluna `step_type`/estrutura em lista existe para permitir múltiplas queries por análise no futuro, sem necessidade de migration).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `analysis_id` | UUID (FK → `analyses.id`, `ON DELETE CASCADE`) | ✅ | A qual análise essa etapa pertence |
| `step_order` | INT | ✅ | Ordem de execução (1, 2, 3...) — único por análise |
| `step_type` | VARCHAR(50) | ✅ | Único valor em uso em V1.0: `query` |
| `definition` | JSONB | ✅ | `{sql, params, ...}` — o SQL parametrizado e seus metadados |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` |

**Constraint:** `UNIQUE(analysis_id, step_order)` — não pode haver duas etapas com a mesma ordem na mesma análise.

**Relacionamentos:** N:1 com `analyses`. Se a análise for excluída, suas etapas são excluídas em cascata.

---

### 2.4 `analysis_versions` — Versões de Análises

Snapshot completo de uma análise em um ponto no tempo, para permitir histórico e rollback (F9/F10).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `analysis_id` | UUID (FK → `analyses.id`) | ✅ | A qual análise essa versão pertence |
| `version_number` | INT | ✅ | Número sequencial da versão (1, 2, 3...) |
| `full_definition` | JSONB | ✅ | Snapshot completo da análise + steps naquele momento |
| `changes_summary` | TEXT | — | Descrição textual do que mudou ("por que mudou") |
| `changed_by` | VARCHAR(255) | — | Quem fez a mudança |
| `is_active` | BOOLEAN | — | Default `true`. Marca qual versão está "em uso" no momento |
| `created_at` | TIMESTAMP | — | Default `NOW()` |

**Constraint:** `UNIQUE(analysis_id, version_number)`.

**Relacionamentos:** N:1 com `analyses`. Referenciada por `execution_history.analysis_version_id` (para saber qual versão específica gerou cada execução).

---

### 2.5 `execution_history` — Histórico de Execuções (Simplificado)

Registro de cada execução de análise. **Importante:** em V1.0 não há identificação de usuário nem de cliente MCP (ver NEGOCIO.md §9 T5) — o log é apenas *o quê* foi executado, *quando* e *com que resultado*.

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `analysis_id` | UUID (FK → `analyses.id`) | ✅ | Qual análise foi executada |
| `analysis_version_id` | UUID (FK → `analysis_versions.id`) | — | Qual versão específica foi usada (pode ser nulo) |
| `parameters` | JSONB | — | Parâmetros com que a análise foi chamada |
| `status` | VARCHAR(50) | — | `success`, `failed`, `timeout` (também usado para o caso `volume_exceeded`, ver ARQUITETURA.md §3.4) |
| `execution_time_ms` | INT | — | Tempo total de execução em milissegundos |
| `rows_affected` | INT | — | Quantidade de linhas retornadas |
| `result_size_bytes` | INT | — | Tamanho do resultado serializado |
| `error_message` | TEXT | — | Mensagem de erro, se houver |
| `result_location` | VARCHAR(500) | — | Path/URI do resultado, se armazenado fora da tabela |
| `executed_at` | TIMESTAMP | — | Default `NOW()` |
| `cached` | BOOLEAN | — | Default `false`. Indica se o resultado veio do cache (F7) |

**Relacionamentos:** N:1 com `analyses` e, opcionalmente, N:1 com `analysis_versions`.

---

## 3. Formato de `analyses.parameters` (JSONB)

Cada chave é o nome de um parâmetro aceito pela análise:

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

Este formato é convertido para JSON Schema MCP (para `list_tools`) e para um `pydantic.BaseModel` (para validação no Execution Engine) pelo módulo `schemas/analysis_parameters.py` — fonte única de verdade para os dois usos.

> O parâmetro reservado `confirmar_volume_alto` (Controle de Volume, ARQUITETURA.md §3.4) **não** faz parte deste JSON — é injetado diretamente no `inputSchema` de toda tool MCP pelo `mcp_transport/tools.py`, por ser global e não específico de uma análise.

---

## 4. Formato de `data_sources.connection_config` (JSONB)

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

O campo `password` (e demais credenciais sensíveis) é cifrado com **Fernet** (biblioteca `cryptography`) antes de persistir — nunca em texto puro (ver ARQUITETURA.md §8.2).

---

## 5. Índices

```sql
CREATE INDEX idx_analyses_active ON analyses(is_active);
CREATE INDEX idx_execution_history_analysis ON execution_history(analysis_id);
CREATE INDEX idx_execution_history_executed_at ON execution_history(executed_at);
CREATE INDEX idx_versions_analysis ON analysis_versions(analysis_id);
```

---

## 6. O Que Foi Removido do Schema (Histórico)

Para não haver confusão ao ler versões antigas de código/specs:

- ❌ `custom_handlers` — removida na revisão v1.9 do ARQUITETURA.md, junto com toda a camada de Handlers Python (ADR-005 reescrito — servidor entrega dataset bruto).
- ❌ `mcp_clients`, `users`, `user_api_keys` — removidas na v1.2, junto com as colunas `user_id`, `username`, `client_llm_name`, `client_llm_version`, `client_identifier` em `execution_history`. A especificação completa (com middleware, repositórios etc.) está preservada como referência em FEATURES_ROADMAP.md §9 (Backlog Futuro — FB1/FB2), para quando o requisito de autenticação voltar ao escopo (fora da rede interna confiável).

---

**Fonte:** ARQUITETURA.md v1.12, §2.2–§2.3 e §8.2.
