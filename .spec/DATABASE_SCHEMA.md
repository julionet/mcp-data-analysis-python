# 🗄️ Esquema do Banco de Dados

## Plataforma de Análise de Dados Genérica com MCP

**Referência:** ARQUITETURA.md §2.2, §2.3 e §3.5 (v1.17)
**Banco:** `analysis_config` (PostgreSQL local — config DB, separado dos data sources de negócio)
**Data:** 2026-10-03 (F14: `execution_history.error_code`, status `timeout`/`error` documentados; bancos existentes precisam do `ALTER TABLE` da §2.5) · 2026-09-30 (F12 implementada — `database/schema.sql` atualizado; migrations e seed da F12 canceladas — `schema.sql` é a única fonte (F13, decisão 7); atualizado — F12: `users.password_hash` (login por e-mail e senha); tabelas `users`, `profiles`, `user_profiles`, `profile_analyses`, `access_tokens`; `execution_history` ganha `user_id`)

> Este documento descreve apenas o **banco de configuração** da própria plataforma (onde ficam análises, histórico etc.). Os bancos de negócio conectados como `data_sources` (PostgreSQL/MySQL/SQL Server/Oracle dos clientes) não têm schema fixo — são externos e arbitrários.

---

## 1. Diagrama de Relacionamento (Visão Geral)

```
data_sources (1) ──────< (N) analyses
                              │
                              ├──────< (N) analysis_steps
                              │
                              ├──────< (N) execution_history
                              │                        │
                              │                        │ (0..1, F12)
                              │                        ▼
                              │                     users >──────< (N:N via user_profiles) profiles
                              │                        │                                      │
                              │                        │ (1:N)                       (N:N via profile_analyses)
                              │                        ▼                                      │
                              │                 access_tokens                                 │
                              └────────────────────────────────────────────────────────────────┘
                                        (profile_analyses vincula profiles <-> analyses)
```

- Uma **análise** pertence a exatamente uma **fonte de dados** (`data_sources`).
- Uma **análise** tem N **etapas** (`analysis_steps`) — em V1.0, sempre uma etapa do tipo `query`.
- Cada **execução** (`execution_history`) referencia a análise executada e, desde F12, opcionalmente qual **usuário** (`user_id`) a executou.
- Um **usuário** (`users`, F12) tem N **tokens de acesso** (`access_tokens`) e está vinculado a N **perfis** (`profiles`) via `user_profiles`.
- Um **perfil** está vinculado a N **analyses** via `profile_analyses` — a permissão efetiva de um usuário é a união das analyses ativas de todos os seus perfis ativos (ver ARQUITETURA.md §3.5).

---

## 2. Tabelas

### 2.1 `data_sources` — Fontes de Dados

Representa uma conexão a um banco de dados externo (o "de onde" os dados de negócio vêm).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único, gerado automaticamente |
| `name` | VARCHAR(255) | ✅ (UNIQUE) | Nome único da fonte de dados (ex.: `"vendas_db"`) |
| `type` | VARCHAR(50) | ✅ | Tipo do banco: `postgresql`, `mysql`, `sqlserver`, `oracle`, `api` |
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
- 1:N com `analysis_steps`, `execution_history`

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

### 2.4 *(removida)*

A tabela `analysis_versions` saiu do schema na v1.17 (ver §6). A numeração foi mantida para não quebrar as referências a §2.5-§2.10.

---

### 2.5 `execution_history` — Histórico de Execuções

Registro de cada execução de análise — *o quê* foi executado, *quando*, *com que resultado* e, desde F12, *por quem* (quando disponível).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `analysis_id` | UUID (FK → `analyses.id`) | ✅ | Qual análise foi executada |
| `user_id` | UUID (FK → `users.id`, sem `ON DELETE` — `NO ACTION`) | — | Quem executou (F12). `NULL` para execuções anteriores a F12. **Impede apagar o usuário** enquanto houver execuções dele (preserva a auditoria) — ver §2.6 |
| `parameters` | JSONB | — | Parâmetros com que a análise foi chamada |
| `status` | VARCHAR(50) | — | `success`, `volume_exceeded` (ver ARQUITETURA.md §3.4), `error` ou `timeout` (F14). O valor `failed`, citado em versões antigas, nunca foi gravado |
| `execution_time_ms` | INT | — | Tempo total de execução em milissegundos |
| `rows_affected` | INT | — | Quantidade de linhas retornadas |
| `result_size_bytes` | INT | — | Tamanho do resultado serializado |
| `error_message` | TEXT | — | Mensagem de erro, se houver |
| `result_location` | VARCHAR(500) | — | Path/URI do resultado, se armazenado fora da tabela |
| `executed_at` | TIMESTAMP | — | Default `NOW()` |
| `cached` | BOOLEAN | — | Default `false`. Indica se o resultado veio do cache (F7) |
| `error_code` | VARCHAR(50) | — | Código estável do erro (F14): `ANALYSIS_NOT_FOUND`, `INVALID_PARAMETERS`, `INVALID_ANALYSIS_CONFIG`, `DATA_SOURCE_UNAVAILABLE`, `QUERY_TIMEOUT`, `QUERY_FAILED`, `INTERNAL_ERROR` (ver ARQUITETURA.md §3.4.1). `NULL` quando não houve erro e em linhas anteriores à F14 |

**Bancos já criados (pré-F14):** sem migration (decisão do projeto) — executar uma vez, direto no banco:
```sql
ALTER TABLE execution_history ADD COLUMN error_code VARCHAR(50);
```
**Atenção:** sem essa coluna o `INSERT` do `ExecutionRepository` falha, e o `AuditService` só loga o erro (não derruba a resposta) — o histórico deixaria de ser gravado.

**Relacionamentos:** N:1 com `analyses`, e, desde F12, opcionalmente N:1 com `users`.

---

### 2.6 `users` — Usuários com Acesso à Plataforma (F12)

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `name` | VARCHAR(255) | ✅ | Nome do usuário |
| `external_id` | VARCHAR(255) | — (UNIQUE) | **E-mail de login (F12)**, cadastrado sempre em minúsculas; a aplicação normaliza (`strip().lower()`) o e-mail recebido em `POST /auth/token`/`/auth/revoke` antes de buscar. Sem `CHECK` no banco — cadastro com maiúscula nunca casa com o login |
| `password_hash` | VARCHAR(255) | — | **Hash bcrypt da senha (F12)**, nunca a senha. `NULL` = usuário não consegue emitir token. Gerado fora do código e inserido à mão (ver F12 §8.2) |
| `is_blocked` | BOOLEAN | ✅ (NOT NULL) | Default `false`. Bloqueado perde acesso imediato a todas as analyses (ver ARQUITETURA.md §3.5) |
| `created_by` | VARCHAR(255) | — | Quem criou o registro |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` |

**Relacionamentos:** 1:N com `access_tokens`; N:N com `profiles` via `user_profiles`; referenciado por `execution_history.user_id`.

**Exclusão de usuário:** `DELETE FROM users` **falha** (violação de FK) se o usuário tiver alguma linha em `execution_history` — decisão deliberada, para nunca perder o rastro de quem executou o quê. Vínculos em `user_profiles` e `access_tokens` têm `ON DELETE CASCADE` e são apagados junto. Para tirar o acesso de alguém que já executou análises, o caminho é `UPDATE users SET is_blocked = true` (efeito imediato, ver ARQUITETURA.md §3.5), e não apagar.

---

### 2.7 `profiles` — Perfis de Acesso (F12)

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `name` | VARCHAR(255) | ✅ (UNIQUE) | Nome do perfil (ex.: `"Comercial"`) |
| `description` | TEXT | — | Descrição do perfil |
| `is_active` | BOOLEAN | ✅ (NOT NULL) | Default `true`. Perfil inativo não libera nenhuma analysis, mesmo que o vínculo em `profile_analyses` exista |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` |

**Relacionamentos:** N:N com `users` via `user_profiles`; N:N com `analyses` via `profile_analyses`.

---

### 2.8 `user_profiles` — Vínculo N:N Usuário ↔ Perfil (F12)

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `user_id` | UUID (FK → `users.id`, `ON DELETE CASCADE`) | ✅ (PK composta) | Usuário vinculado |
| `profile_id` | UUID (FK → `profiles.id`, `ON DELETE CASCADE`) | ✅ (PK composta) | Perfil vinculado |

**Constraint:** `PRIMARY KEY (user_id, profile_id)` — um usuário não pode ter o mesmo perfil vinculado duas vezes.

---

### 2.9 `profile_analyses` — Vínculo N:N Perfil ↔ Analyses (F12)

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `profile_id` | UUID (FK → `profiles.id`, `ON DELETE CASCADE`) | ✅ (PK composta) | Perfil vinculado |
| `analysis_id` | UUID (FK → `analyses.id`, `ON DELETE CASCADE`) | ✅ (PK composta) | Análise liberada pelo perfil |

**Constraint:** `PRIMARY KEY (profile_id, analysis_id)`.

**Nota:** a permissão efetiva de um usuário é a união das analyses ativas de todos os perfis ativos vinculados a ele — recalculada em toda chamada MCP, nunca cacheada (ver ARQUITETURA.md §3.5).

---

### 2.10 `access_tokens` — Tokens de Acesso (F12)

Token **opaco** — só o hash é persistido, nunca o valor bruto (ver ARQUITETURA.md ADR-007).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `user_id` | UUID (FK → `users.id`, `ON DELETE CASCADE`) | ✅ | Dono do token |
| `token_hash` | CHAR(64) | ✅ (UNIQUE) | SHA-256 hex do token bruto (`secrets.token_urlsafe(32)`) |
| `label` | VARCHAR(255) | — | Identifica de qual cliente MCP é esse token (ex.: `"Claude Desktop - notebook Julio"`) |
| `expires_at` | TIMESTAMPTZ | ✅ | Expiração — default 90 dias na emissão (`ACCESS_TOKEN_EXPIRATION_DAYS`) |
| `revoked_at` | TIMESTAMPTZ | — | Preenchido se revogado manualmente antes de expirar |
| `created_at` | TIMESTAMPTZ | — | Default `NOW()` |
| `last_used_at` | TIMESTAMPTZ | — | Atualizado a cada autenticação bem-sucedida (observabilidade) |

**Relacionamentos:** N:1 com `users`.

**Fuso:** as 4 datas desta tabela são `TIMESTAMPTZ` (o resto do schema usa `TIMESTAMP`), porque o asyncpg devolve `TIMESTAMP` sem fuso e a validação de expiração compara com `datetime.now(timezone.utc)`.

**Emissão, renovação e revogação:** pelo próprio usuário, via `POST /auth/token` (e-mail + senha; `label` e `expire_days` opcionais) e `POST /auth/revoke` — ver ARQUITETURA.md §3.5, ADR-007 e `features/F12_AUTENTICACAO_PERFIS.md`. O `label` é texto livre informado pelo usuário no pedido de emissão.

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
CREATE INDEX idx_execution_history_user ON execution_history(user_id);
-- (sem índice em token_hash: o UNIQUE de access_tokens.token_hash já cria um índice)
CREATE INDEX idx_access_tokens_user ON access_tokens(user_id);
```

---

## 6. O Que Foi Removido do Schema (Histórico)

Para não haver confusão ao ler versões antigas de código/specs:

- ❌ `custom_handlers` — removida na revisão v1.9 do ARQUITETURA.md, junto com toda a camada de Handlers Python (ADR-005 reescrito — servidor entrega dataset bruto).
- ❌ `analysis_versions` e `execution_history.analysis_version_id` — removidas na v1.17 (a coluna era mantida como NULL "para compatibilidade futura"; sem a tabela, não fazia sentido). Se o versionamento (FB6/FB7) for reintroduzido, volta com uma migration. Bancos já criados com o schema antigo precisam de: `ALTER TABLE execution_history DROP COLUMN analysis_version_id; DROP TABLE analysis_versions;`.
- ❌ `mcp_clients` — removida na v1.2 junto com as colunas `client_llm_name`, `client_llm_version`, `client_identifier` em `execution_history`; segue fora de escopo (FB1, identificação de cliente MCP/software — diferente de identificação de usuário, já implementada via F12).
- ❌ `user_api_keys` — desenho original de FB2 (v1.2), API Key direta por usuário sem perfis; **não voltou** — F12 usa `access_tokens` (token opaco com hash) em vez disso.
- ✅ `users` e `execution_history.user_id`, removidas na v1.2, **voltaram na revisão de 2026-09-29 (F12)** com um desenho revisado: perfis N:N (`profiles`, `user_profiles`, `profile_analyses`) em vez de API Key + quota direta — ver ARQUITETURA.md ADR-007 e §2.6-§2.10 acima.

---

**Fonte:** ARQUITETURA.md v1.17, §2.2, §2.3 e §3.5.
