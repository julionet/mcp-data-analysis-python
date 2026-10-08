# 🗄️ Esquema do Banco de Dados

## Plataforma de Análise de Dados Genérica com MCP

**Referência:** ARQUITETURA.md §2.2, §2.3, §2.4 e §3.5 (v1.26)
**Banco:** `analysis_config` (PostgreSQL — config DB, separado dos data sources de negócio; nome real definido por `POSTGRES_CONFIG_DATABASE` no `.env`). **Fonte única do DDL:** `src/database/schema.sql` (sem migrations)
**Data:** 2026-10-08 (F23, API administrativa: `users.is_admin` em §2.6 + `ALTER TABLE` para bancos existentes, seed do admin marcado `is_admin = true` em §6, convenções em §8) · 2026-10-05 (alinhado ao código: §2.1 `type` aceito pelo `AdapterFactory`, §2.3 `definition` = `{sql, params}`, §2.5 `result_location` sempre `NULL`, §3 regras de validação de `parameters`, §4 `connection_config` por banco, §6 seed do admin com `pgcrypto`, §8 convenções — `updated_at` sem trigger) · 2026-10-03 (F14: `execution_history.error_code`, status `timeout`/`error` documentados; bancos existentes precisam do `ALTER TABLE` da §2.5) · 2026-09-30 (F12 implementada — `database/schema.sql` atualizado; migrations e seed da F12 canceladas — `schema.sql` é a única fonte (F13, decisão 7); atualizado — F12: `users.password_hash` (login por e-mail e senha); tabelas `users`, `profiles`, `user_profiles`, `profile_analyses`, `access_tokens`; `execution_history` ganha `user_id`)

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
| `type` | VARCHAR(50) | ✅ | Tipo do banco. **Aceitos pelo `AdapterFactory`:** `postgresql`, `mysql`, `sqlserver`, `oracle`. Qualquer outro valor (inclusive `api`, citado em versões antigas, que não tem adapter) falha na execução com `ValueError` → `DATA_SOURCE_UNAVAILABLE`. Sem `CHECK` no banco |
| `connection_config` | JSONB | ✅ | Conexão do data source; as chaves variam por banco, e `password` vai cifrado com Fernet — ver §4 |
| `is_active` | BOOLEAN | — | Default `true`. **Fonte inativa (ou inexistente) faz a execução da análise falhar** com `DATA_SOURCE_UNAVAILABLE` ("não encontrado ou inativo") |
| `created_by` | VARCHAR(255) | — | Quem criou o registro |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` |

**Relacionamentos:** referenciada por `analyses.data_source_id` (1 fonte → N análises).

**Gestão pela API (F24):** `POST/PATCH /admin/data-sources` cifram `connection_config.password` (Fernet) e rejeitam chaves desconhecidas para o `type`; alterar `connection_config` ou `is_active` atualiza o `updated_at` das analyses da fonte (o cache não conhece o data source). Em `postgresql`, o par efetivo `pool_min_size ≤ pool_max_size` (valor informado ou padrão `PG_POOL_*` do `.env`) é validado.

---

### 2.2 `analyses` — Análises (Definições)

A definição de "o que" uma análise faz — nome, descrição, de onde vêm os dados e quais parâmetros aceita. Não guarda o SQL diretamente (isso fica em `analysis_steps`).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `name` | VARCHAR(255) | ✅ (UNIQUE) | Nome único da análise (ex.: `"vendas_por_regiao"`) — é o nome exposto como tool MCP |
| `description` | TEXT | — | Descrição usada pelo LLM cliente para entender o que a análise faz |
| `data_source_id` | UUID (FK → `data_sources.id`, sem `ON DELETE`) | — (na prática ✅) | Qual fonte de dados essa análise consulta. Nulável no DDL, mas sem fonte a execução falha com `DATA_SOURCE_UNAVAILABLE`. Não dá para apagar uma fonte que ainda tem análises |
| `cache_frequency` | VARCHAR(50) | — | Default `'daily'`. TTL do cache (F7): `hourly`=1h, `daily`=24h, `weekly`=7d, `none`=sem cache. **Outro valor** → `INVALID_ANALYSIS_CONFIG` e nenhuma query executada (validação só em código, sem `CHECK`) |
| `parameters` | JSONB | — | Schema dos parâmetros aceitos (ver §3) — convertido para JSON Schema MCP e para modelo Pydantic |
| `is_active` | BOOLEAN | — | Default `true`. Análise inativa some do `list_tools()` e não executa (`ANALYSIS_NOT_FOUND`) |
| `created_by` | VARCHAR(255) | — | Quem criou/configurou a análise |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()`. **Entra na chave do cache (F7)** — e **não é atualizado sozinho** (sem trigger; ver §8): ao editar a análise ou seu step por SQL, faça `updated_at = NOW()` junto, senão o cache serve o resultado antigo até o TTL expirar |

**Relacionamentos:**
- N:1 com `data_sources` (uma análise pertence a uma fonte)
- 1:N com `analysis_steps` (`ON DELETE CASCADE`) e `profile_analyses` (`ON DELETE CASCADE`)
- 1:N com `execution_history` (**sem** `ON DELETE`): **uma análise com histórico não pode ser apagada** — desative com `is_active = false`

---

### 2.3 `analysis_steps` — Etapas da Análise

O SQL efetivo que a análise executa. Em V1.0, toda análise tem exatamente 1 step do tipo `query` (a coluna `step_type`/estrutura em lista existe para permitir múltiplas queries por análise no futuro, sem necessidade de migration).

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `analysis_id` | UUID (FK → `analyses.id`, `ON DELETE CASCADE`) | ✅ | A qual análise essa etapa pertence |
| `step_order` | INT | ✅ | Ordem de execução (1, 2, 3...) — único por análise. **O engine executa só o primeiro step** (menor `step_order`) |
| `step_type` | VARCHAR(50) | ✅ | Único valor em uso em V1.0: `query`. O código **não lê** esta coluna (os comentários `transform`/`aggregate` do `schema.sql` são legado dos handlers removidos) |
| `definition` | JSONB | ✅ | `{"sql": "...", "params": ["nome1", "nome2"]}` — ver abaixo |

**`definition` (chaves lidas pelo engine):**
- `sql` — SELECT com placeholders `:nome`, traduzido por adapter. Validado antes de executar: só `SELECT`, **sem `;`**, sem palavras proibidas (DML/DDL) → senão `INVALID_ANALYSIS_CONFIG`.
- `params` — lista **ordenada** com os nomes dos parâmetros usados no SQL (define a ordem dos placeholders posicionais). Todo nome precisa existir em `analyses.parameters`; para rodar nos 4 bancos, todo parâmetro declarado deve aparecer no SQL.
- A chave `handler` (versões antigas) não existe mais.
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` |

**Constraint:** `UNIQUE(analysis_id, step_order)` — não pode haver duas etapas com a mesma ordem na mesma análise.

**Relacionamentos:** N:1 com `analyses`. Se a análise for excluída, suas etapas são excluídas em cascata.

---

### 2.4 *(removida)*

A tabela `analysis_versions` saiu do schema na v1.17 (ver §7). A numeração foi mantida para não quebrar as referências a §2.5-§2.10.

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
| `rows_affected` | INT | — | Linhas retornadas (`success`). Em `volume_exceeded` guarda a **estimativa** de linhas; em erro/timeout fica `NULL` |
| `result_size_bytes` | INT | — | Tamanho do JSON serializado (`success`) ou a estimativa em bytes (`volume_exceeded`); `NULL` em erro/timeout |
| `error_message` | TEXT | — | Mensagem de erro, se houver |
| `result_location` | VARCHAR(500) | — | Reservada: o `AuditService` grava sempre `NULL` (resultado nunca é armazenado fora da tabela em V1.0) |
| `executed_at` | TIMESTAMP | — | Default `NOW()` (não existe coluna `created_at` nesta tabela) |
| `cached` | BOOLEAN | — | Default `false`. `true` só quando o resultado foi servido do cache (F7); erros e `volume_exceeded` sempre `false` |
| `error_code` | VARCHAR(50) | — | Código estável do erro (F14): `ANALYSIS_NOT_FOUND`, `INVALID_PARAMETERS`, `INVALID_ANALYSIS_CONFIG`, `DATA_SOURCE_UNAVAILABLE`, `QUERY_TIMEOUT`, `QUERY_FAILED`, `INTERNAL_ERROR` (ver ARQUITETURA.md §3.4.1). `NULL` quando não houve erro e em linhas anteriores à F14 |

**Bancos já criados (pré-F14):** sem migration (decisão do projeto) — executar uma vez, direto no banco:
```sql
ALTER TABLE execution_history ADD COLUMN error_code VARCHAR(50);
```
**Atenção:** sem essa coluna o `INSERT` do `ExecutionRepository` falha, e o `AuditService` só loga o erro (não derruba a resposta) — o histórico deixaria de ser gravado.

**Relacionamentos:** N:1 com `analyses`, e, desde F12, opcionalmente N:1 com `users`.

**Quando NÃO há linha:** análise inexistente/acesso negado (`ANALYSIS_NOT_FOUND`) não grava histórico — não há `analysis_id` válido para a FK.

---

### 2.6 `users` — Usuários com Acesso à Plataforma (F12)

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | UUID (PK) | ✅ | Identificador único |
| `name` | VARCHAR(255) | ✅ | Nome do usuário |
| `external_id` | VARCHAR(255) | — (UNIQUE) | **E-mail de login (F12)**, cadastrado sempre em minúsculas; a aplicação normaliza (`strip().lower()`) o e-mail recebido em `POST /auth/token`/`/auth/revoke` antes de buscar. Sem `CHECK` no banco — cadastro com maiúscula nunca casa com o login |
| `password_hash` | VARCHAR(255) | — | **Hash bcrypt da senha (F12)**, nunca a senha. `NULL` = usuário não consegue emitir token. Gerado fora do código e inserido à mão (ver F12 §8.2); o usuário `admin` do seed (§6) é gerado com `crypt(..., gen_salt('bf', 12))` do `pgcrypto` |
| `is_blocked` | BOOLEAN | ✅ (NOT NULL) | Default `false`. Bloqueado perde acesso imediato a todas as analyses (ver ARQUITETURA.md §3.5) |
| `is_admin` | BOOLEAN | ✅ (NOT NULL) | Default `false`. **Papel administrativo (F23, ADR-008):** só quem tem `true` usa as rotas `/admin/*`. Independente dos perfis de acesso a analyses; lido do BD a cada chamada, nunca do token. O usuário `admin` do seed (§6) é gravado com `true` |
| `created_by` | VARCHAR(255) | — | Quem criou o registro |
| `created_at` | TIMESTAMP | — | Default `NOW()` |
| `updated_at` | TIMESTAMP | — | Default `NOW()` |

**Bancos já criados (pré-F23):** sem migration (decisão do projeto) — executar uma vez, direto no banco:
```sql
ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false;
```
Sem ela, reexecutar o seed do admin (`seed_admin.sh` / `setup-admin`) falha. A coluna já consta de `schema.sql`; a API que a usa (`/admin/*`, F23) ainda não está implementada.

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

**Regras validadas a cada execução (`validate_schema`)** — violação → `INVALID_ANALYSIS_CONFIG`:
- `type` ∈ {`string`, `integer`, `number`, `boolean`, `date`, `datetime`} (obrigatório).
- `required` deve ser booleano (default `false`).
- `enum` só em `string`, `integer` ou `number`.
- `min`/`max` só em `integer` ou `number` (viram `ge`/`le` no Pydantic e `minimum`/`maximum` no JSON Schema).

**Semântica:** parâmetro com `required: true` não tem default; os demais são opcionais e assumem `default` (ou `null`). `description` e `default` são opcionais. Valor do cliente fora das regras → `INVALID_PARAMETERS`. Os parâmetros validados (com defaults resolvidos) são os que entram na chave do cache.

> O parâmetro reservado `confirmar_volume_alto` (Controle de Volume, ARQUITETURA.md §3.4) **não** faz parte deste JSON — é injetado diretamente no `inputSchema` de toda tool MCP pelo `mcp_transport/tools.py`, por ser global e não específico de uma análise.

---

## 4. Formato de `data_sources.connection_config` (JSONB)

```json
{
  "host": "192.168.1.10",
  "port": 5432,
  "database": "vendas_db",
  "user": "readonly_user",
  "password": "<cifrado com Fernet>"
}
```

Chaves lidas por cada adapter (as demais são ignoradas):

| `type` | Obrigatórias | Opcionais (default) |
|---|---|---|
| `postgresql` | `host`, `port`, `database`, `user`, `password` | — |
| `mysql` | `host`, `database`, `user`, `password` | `port` (3306) |
| `sqlserver` | `host`, `database`, `user`, `password` | `port` (1433), `driver` (`ODBC Driver 18 for SQL Server`), `sslmode` (`prefer` → `Encrypt=yes;TrustServerCertificate=yes`; `verify-full` → `TrustServerCertificate=no`; outro valor falha) |
| `oracle` | `host`, `user`, `password` e **`service_name` ou `sid`** | `port` (1521) |

`sslmode` só tem efeito no SQL Server; nos demais é ignorado.

O campo `password` é cifrado com **Fernet** (chave `FERNET_KEY` do `.env`; biblioteca `cryptography`) antes de persistir — nunca em texto puro (ver ARQUITETURA.md §8.2). O `AnalysisService` decifra no momento de criar o adapter; uma `FERNET_KEY` diferente da usada no cadastro faz a conexão falhar.

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

## 6. Extensões e Seed (não fazem parte do `schema.sql`)

O `schema.sql` **não** cria extensões nem dados. O seed do administrador (`src/database/seed_admin.sh`) é montado em `docker-entrypoint-initdb.d` dos compose **local** e **dist** (não no **remote**), roda depois do `schema.sql` e é **idempotente** (`ON CONFLICT DO NOTHING`); `scripts/setup-admin.ps1` o reexecuta em bancos já existentes.

- `CREATE EXTENSION IF NOT EXISTS pgcrypto;` — necessária só para o seed (`crypt`/`gen_salt` geram o bcrypt). A aplicação em si não usa.
- `profiles`: perfil `admin`.
- `users`: usuário `admin` (`ADMIN_LOGIN`, padrão `admin`; `external_id` sempre em minúsculas; `created_by = 'seed_admin'`), senha `ADMIN_PASSWORD` — **padrão conhecido `Senh@123`: trocar em qualquer ambiente acessível por outras pessoas** (`ADMIN_RESET_PASSWORD=1` ou `setup-admin.ps1 -ResetPassword` regrava a senha).
  O usuário é gravado com `is_admin = true` (F23) e, se já existia sem o papel, o seed o atualiza (`UPDATE ... WHERE is_admin = false`) — reexecutar o seed volta a marcá-lo administrador.
- `user_profiles`: vínculo admin ↔ `admin`. (O perfil `admin` é de **acesso a analyses**; o papel administrativo é `users.is_admin` — são independentes, ADR-008.)
- `profile_analyses`: perfil `admin` ↔ **todas as análises existentes no momento**. Análises cadastradas depois **não** entram sozinhas: reexecute o seed ou faça `INSERT` em `profile_analyses`.
- O seed **não** emite token (o token só existe na resposta de `POST /auth/token`).

---

## 7. O Que Foi Removido do Schema (Histórico)

Para não haver confusão ao ler versões antigas de código/specs:

- ❌ `custom_handlers` — removida na revisão v1.9 do ARQUITETURA.md, junto com toda a camada de Handlers Python (ADR-005 reescrito — servidor entrega dataset bruto).
- ❌ `analysis_versions` e `execution_history.analysis_version_id` — removidas na v1.17 (a coluna era mantida como NULL "para compatibilidade futura"; sem a tabela, não fazia sentido). Se o versionamento (FB6/FB7) for reintroduzido, volta com uma migration. Bancos já criados com o schema antigo precisam de: `ALTER TABLE execution_history DROP COLUMN analysis_version_id; DROP TABLE analysis_versions;`.
- ❌ `mcp_clients` — removida na v1.2 junto com as colunas `client_llm_name`, `client_llm_version`, `client_identifier` em `execution_history`; segue fora de escopo (FB1, identificação de cliente MCP/software — diferente de identificação de usuário, já implementada via F12).
- ❌ `user_api_keys` — desenho original de FB2 (v1.2), API Key direta por usuário sem perfis; **não voltou** — F12 usa `access_tokens` (token opaco com hash) em vez disso.
- ✅ `users` e `execution_history.user_id`, removidas na v1.2, **voltaram na revisão de 2026-09-29 (F12)** com um desenho revisado: perfis N:N (`profiles`, `user_profiles`, `profile_analyses`) em vez de API Key + quota direta — ver ARQUITETURA.md ADR-007 e §2.6-§2.10 acima.

---

## 8. Convenções do Schema

- **Sem triggers:** nenhum `updated_at` é atualizado automaticamente — quem edita por SQL deve setá-lo. Só `analyses.updated_at` tem efeito funcional (chave do cache, F7); `users.updated_at` é gravado só pelo seed ao regravar a senha.
- **Sem migrations:** o `schema.sql` é a única fonte; mudanças em bancos existentes são `ALTER TABLE` manuais, registrados na seção da tabela (ex.: `execution_history.error_code`, §2.5; `users.is_admin`, §2.6).
- **Sem `CHECK`:** valores como `data_sources.type`, `analyses.cache_frequency`, `execution_history.status` são validados só em código.
- **Fuso:** `access_tokens` usa `TIMESTAMPTZ`; as demais tabelas, `TIMESTAMP`.
- **Cascata:** `analysis_steps`, `user_profiles`, `profile_analyses` e `access_tokens` apagam em cascata. `analyses.data_source_id`, `execution_history.analysis_id` e `execution_history.user_id` **não** — preservam a auditoria (bloqueie/desative em vez de apagar). A API administrativa (F23–F25, ARQUITETURA.md §2.4/ADR-008) segue isso: `DELETE` físico só sem dependentes, senão 409 orientando desativar/bloquear.
- **Índices de `execution_history` e a consulta da F25:** os índices atuais (§5) são simples; índices compostos ou GIN em `parameters` só serão criados se o `EXPLAIN` justificar (decisão da F25, ARQUITETURA.md §2.4) — nenhum foi criado ainda. **Medição da F25 (1 M de linhas, 2026-10-08):** GIN em `parameters` não se justifica; o único caso acima da meta (análise + filtro `parameters` raro: 1,5 s) cai para 43 ms com `CREATE INDEX idx_execution_history_analysis_executed_at ON execution_history (analysis_id, executed_at DESC);` — **proposto, aguardando decisão** (F25 §12).

---

**Fonte:** `src/database/schema.sql`, `src/database/seed_admin.sh`, repositórios/adapters em `src/` e ARQUITETURA.md v1.26, §2.2, §2.3, §2.4 e §3.5.
