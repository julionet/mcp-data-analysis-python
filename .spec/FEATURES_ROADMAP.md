# 📦 Roadmap de Features e Template de Especificação

## Plataforma de Análise de Dados Genérica com MCP (Multi-Cliente, Streamable HTTP)

**Versão:** 1.22 (Aprovado — com PostgreSQL + MySQL (F10 ✅ Done) + SQL Server (F11 ✅ Done) + Oracle (F9 ✅ Done), TLS obrigatório, **com Autenticação por Token + Perfis (F12 ✅ Done)**, **sem Handlers — servidor entrega dataset bruto**, sem Versionamento de Análises)
**Data:** 2026-10-08 (atualizado 2026-10-08 — API administrativa: F23 e F24 implementadas, F25 planejada)
**Status:** ✅ Aprovado
**Escopo:** Qualquer cliente MCP via Streamable HTTP **com TLS** (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.)

> **Nota de revisão (v1.21 → v1.22):** adicionadas **F23, F24 e F25 — API Administrativa (`/admin/*`)** para suportar um frontend de gestão (hoje usuários, perfis, data sources e analyses só são cadastrados por INSERT manual; nenhum repositório tem create/update/delete/list). Entram na Sprint 3 **antes de F16/F17/F18** (numeração mantida; a ordem de implementação é F23 → F24 → F25 → F17 → F16 → F18). Decisões: papel admin por coluna `users.is_admin` (ALTER TABLE manual; dependência `require_admin` sobre o Bearer existente, checando BD a cada chamada); erros no formato slug `{"error","message"}` das rotas `/auth/*` (contrato F14 segue só no `/mcp`); DELETE híbrido (físico só sem dependentes, senão 409 sugerindo desativar/bloquear). Esforço +8d (Sprint 3: ~12,5 → ~20,5 dias; projeto: 22 → 25 features, ~31 → ~39 dias). Plano: `~/.claude/plans/j-sei-que-tem-nested-milner.md`; specs a criar em `features/F23_*.md`, `F24_*.md`, `F25_*.md` antes de qualquer código.

> **Nota de revisão (v1.20 → v1.21):** F15 (Performance Optimization) implementada (2026-10-07) e registrada no roadmap; sincronização de partes que ficaram desatualizadas: métrica "Features Implementadas" (13/22 → **15/22**), Timeline (§7) com ✅ em F13, F14 e F15, e "Próximos Passos" (§4) com o estado da Sprint 3 (4/7; restam F16, F17 e F18). F15: pool PostgreSQL configurável (`PG_POOL_MIN/MAX_SIZE`, `CONFIG_DB_POOL_MIN/MAX_SIZE`), `scripts/benchmark.py` e `scripts/load_test.py`; sem cache de token/permissão (F12/ADR-007); nenhum índice criado (EXPLAIN sem evidência); 500/500 testes ✅. Ver `features/F15_PERFORMANCE_OPTIMIZATION.md` §12. Nenhuma feature adicionada, removida ou renumerada; esforços inalterados.

> **Nota de revisão (v1.19 → v1.20):** F14 (Error Handling & Validation) implementada (2026-10-03). Erros ganham `error_code` + `retryable`; timeout de query vira status `timeout`; retry (3x, backoff exponencial) só de falha **rápida** de conexão; `call_tool()`/`list_tools()` nunca vazam exceção; acesso negado é indistinguível de "análise não encontrada"; `execution_history.error_code` (coluna nova — `ALTER TABLE` manual em bancos existentes). Descoberto na F14: o `timeout=` do SQL Server era só *login timeout* (corrigido). RNF4 ajustado em NEGOCIO.md. Ver `features/F14_ERROR_HANDLING_VALIDATION.md`.

> **Nota de revisão (v1.18 → v1.19):** reorganização pós-F13 (2026-10-03). Código em `src/` (era `analysis_app/`); `tests/`, `Dockerfile`, `.dockerignore`, `.env.example`, `requirements*.txt`, `pytest.ini` e `certs/` na raiz; **um único `.env`** (host + compose; `Settings` com `extra="ignore"`); `mcp_prototype/` removido. **Postgres único por padrão:** os compose sobem só `app` + `postgres` (+ `nginx` no remote); **MySQL, SQL Server e Oracle são opcionais**, cada um em `docker/<banco>/docker-compose.<banco>.yml`, sem mudança de código (credenciais vêm de `data_sources.connection_config`). Spec F13 §10 decisões 10 e 11.

> **Nota de revisão (v1.17 → v1.18):** F13 (Docker Setup) **implementada** (2026-10-03). `Dockerfile` (python:3.13-slim-bookworm + `msodbcsql18`, usuário não-root, `HEALTHCHECK`), `docker-compose.local.yml` (`app` + `postgres` + `mysql`, TLS no uvicorn com mkcert montado) e `docker-compose.remote.yml` (`nginx` + `app` + `postgres` + `mysql`; TLS no nginx com certificado montado; `certbot` DNS-01 como **profile opcional**, desligado por falta de domínio/DNS). **SQL Server e Oracle ficam fora dos compose** (opcionais, subida manual: `docker/sqlserver/` e `docker/oracle/`). Migrations/seed da F12 **canceladas** — `schema.sql` é a única fonte do schema (referências removidas dos docs). `SQLServerAdapter` não mudou: `sslmode` omitido/`prefer` aceita o certificado autoassinado. Validado: 3 containers healthy, `/health` ok, ALPN `http/1.1`, schema da F12 criado, MySQL e SQL Server conectam a partir do container, nginx roteia `/mcp`, `/auth/` e `/health`; suíte 336/336. **Pendente de validação manual:** fluxo `/auth/token` → `/mcp` com cliente real, análise completa em MySQL/SQL Server, streaming SSE pelo nginx, Oracle 23ai (pendência da F9) e profile `certbot`. Spec: `features/F13_DOCKER_SETUP.md`.

> **Nota de revisão (v1.16 → v1.17):** requisitos da F13 (Docker Setup) detalhados: um container por artefato — `app`, `postgres`, `mysql` e `oracle`. O container Oracle fica **criado, mas fora da execução do docker-compose** por ora. Ver "F13 em detalhe" na Sprint 3. Esforço (2d) e dependências inalterados.
>
> **Nota de revisão (v1.15 → v1.16):** F9 (Oracle Adapter) **implementada** (2026-10-01). `OracleAdapter` (`adapters/oracle.py`, `python-oracledb` em modo thin, pool async 1/10 com `acquire` de validação no `connect()`) traduz `:x` → `:pN` por índice de `param_names` em passo único, liga `params.values()` a `pN` em `execute_query()`, normaliza chaves de coluna para minúsculas e usa `fetch_lobs=False`/`fetch_decimals=True`; ORA-00911/ORA-00918 são relançados com a explicação do subconjunto comum de SQL. O wrapper do `COUNT(*)` do Volume Guard passou de `AS sub` para `sub` (`analysis_service.py`). Oracle entrou na fixture de `tests/test_adapter_contract.py` (4 adapters × mesmos cenários). Testes: 334 ✅ (27 novos em `tests/test_oracle_adapter.py`). **Sprint 2: 3/3 concluída.** Sem validação manual — não há instância Oracle (F9 §10). Bancos suportados: 3 → 4. Spec e histórico: `features/F9_ORACLE_ADAPTER.md` §11. Próxima: F13 (Docker) e demais da Sprint 3.
>
> **Nota de revisão (v1.14 → v1.15):** F12 **implementada** (2026-09-30): `POST /auth/token` e `POST /auth/revoke` (`routes/auth.py`), `AuthMiddleware` ASGI + `contextvar` no `/mcp` (transporte stateless), `AuthService`, repositórios `UserRepository`/`ProfileRepository`/`AccessTokenRepository`, `list_tools()` filtrado por perfil e `call_tool()` com revalidação de permissão, `execution_history.user_id`. Testes: 295 ✅ (189 anteriores ajustados + 106 novos). Schema em `src/database/schema.sql` (migration e seed da F12 canceladas — F13, decisão 7). Validado com cliente MCP real via `mcp-remote --header`. Spec e notas de implementação: `features/F12_AUTENTICACAO_PERFIS.md` §11. Sprint 3: 1/7 features concluídas. Próximas: F9 (Oracle, Sprint 2) e F13 (Docker, que já deve sair com autenticação obrigatória).
>
> **Nota de revisão (v1.13 → v1.14):** F12 revisada — a emissão de token deixa de ser administrativa (script) e passa a ser **self-service por endpoint**: `POST /auth/token` (e-mail + senha, `label` e `expire_days` opcionais) e `POST /auth/revoke`, em `routes/auth.py`. `users` ganha `password_hash` (bcrypt) e `external_id` vira o e-mail de login. Sem proteção contra tentativas de senha em V1.0 (só log). Esforço de F12: 2.5d → **3.5d** (+1d: endpoints, bcrypt, testes); Sprint 3: ~11.5 → ~12.5 dias; total do projeto: ~30 → ~31 dias. Ver ARQUITETURA.md v1.20 (ADR-007 revisado) e `features/F12_AUTENTICACAO_PERFIS.md`.
>
> **Nota de revisão (v1.12 → v1.13):** F11 (SQL Server Adapter) implementada (2026-09-29). `SQLServerAdapter` (`aioodbc` + `pyodbc`, pool 1/10, autocommit, timeout de query via `settings.query_timeout_seconds`) traduz `:x` → `@x` em `translate_params()` e converte `@x` → `?` na ordem de ocorrência em `execute_query()` (parâmetro repetido e ordem diferente de `param_names` funcionam). Novo `tests/test_adapter_contract.py` garante o mesmo comportamento de parâmetros em PostgreSQL, MySQL e SQL Server — o F9 (Oracle) deve entrar na fixture dele. Sprint 2: 2/3 features concluídas; próxima é F9. Bancos suportados: 2 → 3. Spec e histórico: `features/F11_SQLSERVER_ADAPTER.md` §12.
>
> **Nota de revisão (v1.11 → v1.12):** documento aprovado. Adicionada **F12: Autenticação e Controle de Acesso via Perfis**, retomando e revisando FB2 (UserIdentificationService) e FB4 (RBAC) do Backlog Futuro (§9) — a diferença para o desenho original de FB2/FB4 é a camada intermediária de **perfis** (N:N usuário↔perfil↔analyses) e o mecanismo de token **opaco** (hash SHA-256, não JWT nem OAuth2 — ver ARQUITETURA.md ADR-007 para o racional completo da escolha). F12 entra na Sprint 3, antes do antigo F12 (Docker Setup) — decisão: autenticação é pré-requisito para expor o servidor em produção interna (ARQUITETURA.md §9.2), então precisa existir antes do deploy, mesmo ainda dentro da rede confiável. Todas as features de F12 em diante foram renumeradas em +1 (F12→F13, ..., F21→F22). `execution_history` (F8) ganha `user_id` (nullable, FK → `users.id`) — decisão desta revisão: já que agora existe identificação de usuário, o histórico de execução passa a registrar quem executou cada análise. NEGOCIO.md revisado: nova RF5, RNF5, Restrição T5 e §12 (Roadmap Futuro) — autenticação sai do "Fora de Escopo V1.0"/Roadmap Futuro (V1.1) e entra nesta mesma versão, como F12. ARQUITETURA.md revisado: novo ADR-007, novas tabelas no schema (§2.2), novos componentes (AuthService, UserRepository/ProfileRepository/AccessTokenRepository), nova seção de fluxo (§3.5). DATABASE_SCHEMA.md ganha as tabelas `users`, `profiles`, `user_profiles`, `profile_analyses`, `access_tokens`. Spec completa em `features/F12_AUTENTICACAO_PERFIS.md`.

> **Nota de revisão (v1.10 → v1.11):** F9 deixa de ser "MongoDB Adapter" e passa a ser **"Oracle Adapter"** (Oracle Database 12.1+, `python-oracledb` em modo thin, sem dependência de SO). MongoDB removido de vez do escopo de V1.0 (não vai para o Backlog Futuro). F9 rebaixada de 🟠 Alta para 🟡 Média — não há instância Oracle para teste no momento e a validação manual fica pendente (F9 pode ser dada como Done sem validação manual). Esforço mantido em 1.5d; dependência passa a `F2, F11` (reutiliza `tests/test_adapter_contract.py`, criado no F11). Ordem de implementação da Sprint 2: F10 ✅ → F11 → F9. O F9 também altera `analysis_service.py` (alias do wrapper `COUNT(*)`: `AS sub` → `sub`). Specs: `features/F11_SQLSERVER_ADAPTER.md` e `features/F9_ORACLE_ADAPTER.md`.

> **Nota de revisão (v1.9 → v1.10):** F10 (MySQL Adapter) implementado com sucesso (2026-09-28). Três correções críticas realizadas durante testes: (1) aiomysql usa `%s` não `?`, corrigido em translate_params(); (2) parâmetros reutilizados em query (ex: `:exame` 2 vezes) falhava com `%s` posicional, resolvido com named parameters `%(name)s` (como PostgreSQL $1, $1); (3) conversão de dict em lista quebrava named parameters, corrigido passando dict diretamente. DatabaseAdapter.translate_params() adicionado como método abstrato; PostgreSQLAdapter: `:param` → `$1, $2, ...`; MySQLAdapter: `:param` → `%(param)s`. Refatoração de analysis_service.py completa — _translate_named_params() removida, adapter.translate_params() chamado em _run_query(). Todos os testes passando (23/23). MySQL suportado como data_source type com SQL agnóstico (mesma query funciona em PostgreSQL e MySQL). Script encrypt_credential.py adicionado para criptografar credenciais com Fernet. Próximas: F9 (MongoDB), F11 (SQL Server).

> **Nota de revisão (v1.8 → v1.9):** documento aprovado. Removidas F9 (Version Management) e F10 (Rollback Mechanism) inteiramente da Sprint 2: como a plataforma não implementa Handlers (apenas dataset bruto via servidor), não há necessidade de versionamento de análises nem de rollback — essas features eram um resquício da arquitetura anterior (v1.5 e antes). O requisito O3 (Objetivo Terciário) do NEGOCIO.md foi revisado: "histórico de execuções" (F8, já implementado) é o registro de auditoria necessário; "versionamento de análises" sai do escopo V1.0 e pode ser reintroduzido futuro como FB6/FB7 se a gestão de mudanças em análises se tornar crítica. Total Sprint 2 cai de ~7 dias para ~5d (F11→F21 conservam esforço, mas 3d de F9+F10 desaparecem). Todas as features de Sprint 2 em diante foram renumeradas em -2 (F11→F9, F12→F10, ..., F23→F21).

> **Nota de revisão (v1.7 → v1.8):** documento aprovado. F8 (Log de Execução) foi implementado e testado com 100% de cobertura. `AuditService` persiste em `execution_history`: análise_id, parâmetros, status (success/volume_exceeded/error), execution_time_ms (0 para cache hit), rows_affected, result_size_bytes, error_message, cached flag. AnalysisNotFoundError não é logado em BD (evita violar FK). Critério 5 do F6 (execution_history mostra execuções paralelas sem erro de concorrência) agora pode ser validado. Adicionado método `execute()` abstrato ao `DatabaseAdapter` e implementado em `PostgreSQLAdapter` para operações INSERT/UPDATE/DELETE. Total Sprint 1 permanece ~10.5 dias.

> **Nota de revisão (v1.6 → v1.7):** documento aprovado. Decisão desta sessão: o critério "execution_history mostra as duas execuções, sem erro de concorrência" do F6 (Validação Multi-Cliente) só pode ser validado depois que o F8 (Log de Execução) for implementado — hoje `AuditService.log_execution()` ainda não existe (F8 está ⬜ Todo). F6 pode ser dado como concluído nos critérios 1–4 antes disso, ficando esse critério pendente até a conclusão do F8. Nenhuma mudança de esforço, dependência, status ou numeração de feature.

> **Nota de revisão (v1.5 → v1.6):** documento aprovado. Removida a camada de Handlers Python do servidor (ver NEGOCIO.md v1.6 e ARQUITETURA.md revisão correspondente): o servidor passa a devolver dataset bruto, e é o LLM do cliente MCP quem interpreta/agrega os dados. **F3** deixa de ser "HandlerRegistry e Discovery" e passa a ser **"Controle de Volume de Resultado"** (pré-checagem `COUNT(*)`, checagem de KB, recusa com refinamento ou confirmação explícita) — esforço cai de 2d para 1d. **F14 (Built-in Handlers)** é **removida inteiramente** do Sprint 2 (-2d). F4 (Execution Engine) mantém as mesmas dependências (F2, F3), só que agora F3 é o Controle de Volume, não mais o HandlerRegistry. Todas as features de F15 em diante são renumeradas em -1 (F15→F14, ..., F24→F23) para não deixar buraco. Total geral: 24→**23 features**, ~33→**~30 dias**. Ver `PROPOSTA_REVISAO_HANDLERS_E_VOLUME.md` para o racional completo.

> **Nota de revisão (v1.1 → v1.2):** removidas F6 (Client Identification) e F6B (User Identification) do Sprint 1 — autenticação não faz parte do escopo de V1.0 (ver NEGOCIO.md §9 T5 e ARQUITETURA.md §7 ADR-006). Removida também a "Sprint 1B: Multi-LLM Oficial" inteira: como o transporte é HTTP+SSE (na época) com protocolo MCP padrão, não existe "gateway" por cliente para construir — qualquer cliente compatível já funciona sem adaptação. A validação multi-cliente virou uma feature leve (F6) dentro do próprio Sprint 1. Todas as features foram renumeradas sequencialmente para não deixar buracos (F1...F23). Os números de esforço, que divergiam entre os documentos anteriores, foram recalculados e unificados aqui.

> **Nota de revisão (v1.2 → v1.3):** documento aprovado. Adicionada **F13: SQL Server Adapter** no Sprint 2, ao lado do MongoDB e MySQL adapters. A antiga F13 (Built-in Handlers) passou a F14, e todas as features de Sprint 3/4 foram deslocadas em +1 (antigo F14→F15, ..., antigo F23→F24). Total agora: 24 features, ~33 dias.

> **Nota de revisão (v1.3 → v1.4):** documento aprovado. F1 passa a implementar o servidor MCP via **Streamable HTTP** (endpoint `/mcp`, porta 3000) em vez de HTTP+SSE (endpoint `/sse`). Nenhuma feature foi adicionada, removida ou renumerada — só a descrição técnica de F1 e as URLs de exemplo em F6/timeline mudaram. Ver NEGOCIO.md §9 T4 e ARQUITETURA.md §7 ADR-006.

> **Nota de revisão (v1.4 → v1.5):** documento aprovado. O protótipo F0 confirmou que TLS é obrigatório mesmo em V1.0 (clientes MCP reais recusam `http://` simples — ver NEGOCIO.md §8 RNF5, §9 T1/T4 e ARQUITETURA.md §7 ADR-006). F1 passa a incluir setup de certificado TLS local (mkcert) e negociação ALPN explícita, subindo o esforço estimado de 2d para 2.5d (Sprint 1 passa de ~11 para ~11.5 dias). F6 passa a exigir confirmação de handshake TLS/ALPN bem-sucedido antes do teste com clientes reais, e passa a citar Claude Code (CLI) como um terceiro tipo de cliente MCP já validado, ao lado de apps desktop. Nenhuma feature foi adicionada, removida ou renumerada. Nova nota em §3 registrando as lições técnicas do protótipo F0 para a implementação real de F1.

---

## 1. Roadmap de Features (Priorizado)

### Sprint 1: MVP Local Multi-Cliente (≈ 2 semanas)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F1 | FastAPI + MCP Server Setup via Streamable HTTP **com TLS** | 🔴 Crítica | 2.5d | — | 🟩 Done |
| F2 | PostgreSQL Adapter | 🔴 Crítica | 2d | F1 | 🟩 Done |
| F3 | Controle de Volume de Resultado | 🔴 Crítica | 1d | F2 | 🟩 Done |
| F4 | Analysis Execution Engine | 🔴 Crítica | 2d | F2, F3 | 🟩 Done |
| F5 | MCP Tools Integration (`list_tools` / `call_tool`) | 🔴 Crítica | 1d | F1, F4 | 🟩 Done |
| F6 | Validação Multi-Cliente Simultâneo | 🟠 Alta | 0.5d | F5 | 🟩 Done (critérios 1–4; critério 5 pendente do F8) |
| F7 | Cache Service (In-Memory) | 🟠 Alta | 1d | F4 | 🟩 Done |
| F8 | Log de Execução (Simplificado) | 🟠 Alta | 0.5d | F4 | 🟩 Done |

**Total Sprint 1:** ~10.5 dias (≈ 2 semanas com buffer)

**Destaque:**
- ✅ F1 + F5 garantem servidor MCP agnóstico de cliente, via Streamable HTTP com TLS
- ✅ F3 garante que o servidor nunca devolve um dataset grande demais sem o cliente confirmar o custo de tokens
- ✅ F6 validou na prática que 2+ clientes MCP diferentes conseguem usar o servidor ao mesmo tempo (critérios 1–4); **critério 5 (execution_history sem erro de concorrência) agora pronto para validação após F8**
- ✅ F8 completo: log simples em `execution_history` (análise, parâmetros, status, tempo, cached flag) — sem identificação de usuário/cliente

**F1 em detalhe — itens adicionados após o protótipo F0 (ver ARQUITETURA.md §7 ADR-006):**
```
├─ Certificado TLS local (mkcert) gerado e configurado no servidor
├─ ssl_context_factory programático negociando ALPN (http/1.1) — a CLI padrão
│  do uvicorn não faz isso, e alguns clientes abandonam a conexão sem esse suporte
├─ Rota exata para "/mcp" (sem barra final), além do mount, evitando redirect 307
├─ CORSMiddleware habilitado (necessário mesmo sem navegador tradicional envolvido)
└─ Dependência `mcp` travada com teto de versão (`>=1.9.0,<2.0.0`) — a v2.0.0 remove
   os decorators list_tools()/call_tool() da classe de baixo nível Server
```

**F3 em detalhe (Controle de Volume de Resultado — substitui o antigo "HandlerRegistry e Discovery"):**
```
Objetivo: impedir que uma análise devolva um dataset grande demais para o LLM
cliente processar, sem nunca buscar os dados completos antes de decidir.

Escopo:
├─ Pré-checagem barata: SELECT COUNT(*) com os mesmos filtros da query real
│  ├─ count > DEFAULT_MAX_RESULT_ROWS (.env) → recusa, sem buscar os dados
│  └─ count dentro do limite → segue para a query completa
├─ Segunda checagem: tamanho do resultado serializado em KB
│  └─ excede DEFAULT_MAX_RESULT_SIZE_KB (.env) mesmo com poucas linhas
│     (colunas largas) → recusa com a mesma mensagem
├─ Resposta de recusa estruturada (status "volume_exceeded", com
│  estimativa de linhas/KB e o limite configurado)
└─ Parâmetro reservado `confirmar_volume_alto` (injetado no schema de toda
   tool, não cadastrado em `analyses.parameters`): se true, ignora o limite
   e devolve o dataset completo com um aviso no payload

Sem Registry Pattern, sem discovery de filesystem/banco, sem classes de
handler — um serviço leve (`services/volume_guard_service.py`) chamado pelo
Execution Engine (F4). Ver ARQUITETURA.md (seção de Controle de Volume) e
`PROPOSTA_REVISAO_HANDLERS_E_VOLUME.md` §3 para o mecanismo completo.
```

**F6 em detalhe (Validação Multi-Cliente):**
```
Objetivo: confirmar que o servidor atende múltiplos clientes MCP diferentes,
ao mesmo tempo, sem qualquer configuração de autenticação, via HTTPS.

Critério de aceitação:
├─ Confirmar handshake TLS/ALPN bem-sucedido (ex.: openssl s_client -alpn h2,http/1.1)
│  antes de testar com clientes reais — uma falha de ALPN não gera nenhum log HTTP,
│  só uma conexão abandonada, e é fácil confundir com outro tipo de erro
├─ Configurar pelo menos 2 clientes MCP diferentes (ex.: Claude Desktop + Gemini Desktop
│  ou outro disponível) apontando para a mesma URL https://<ip>:3000/mcp
├─ Pedir a mesma análise nos dois clientes, em paralelo
├─ Ambos recebem resultado correto
└─ execution_history mostra as duas execuções, sem erro de concorrência
   (⚠️ só validável após a conclusão do F8 — Log de Execução / AuditService.log_execution(),
   hoje ⬜ Todo; F6 pode ser dado como concluído nos critérios 1–4 antes disso)

Nota: o protótipo F0 validou com sucesso um terceiro tipo de cliente MCP — o
Claude Code (CLI, via `claude mcp add --transport http`), além de Claude Desktop —
reforçando a evidência de "agnóstico de cliente" além de apps desktop.
```

---

### Sprint 2: Multi-DB (≈ 1 semana)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F9 | Oracle Adapter (via `oracledb`, thin mode) | 🟡 Média | 1.5d | F2, F11 | 🟩 Done |
| F10 | MySQL Adapter | 🟡 Média | 1d | F2 | 🟩 Done |
| F11 | SQL Server Adapter (via ODBC/`aioodbc`) | 🟡 Média | 1.5d | F2 | 🟩 Done |

**Total Sprint 2:** ~3 dias (F10 concluído em 2026-09-27; F11 em 2026-09-29; F9 em 2026-10-01) — ✅ Sprint 2 completa

**Ordem de implementação:** F10 ✅ → F11 ✅ → F9 ✅ (o F9 reutiliza `tests/test_adapter_contract.py`, criado no F11).

**F11 em detalhe (SQL Server Adapter):** requer instalar o driver ODBC nativo da Microsoft (`msodbcsql17`/`18`) no ambiente/imagem Docker antes de usar `pyodbc`/`aioodbc` — isso é uma dependência de sistema operacional, não só de `pip install` (ver ARQUITETURA.md §5.1).

**F9 em detalhe (Oracle Adapter):** `python-oracledb` em modo thin (async nativo, sem Oracle Client no SO), Oracle Database 12.1+. Conexão por DSN montado a partir de `host`/`port`/`service_name` (ou `sid` para bancos antigos); parâmetros `:x` → `:pN` por índice de `param_names` (como o `$n` do PostgreSQL); chaves de coluna normalizadas para minúsculas; `SELECT 1 FROM DUAL` no `test_connection`. `sslmode`/TCPS fora do escopo. Implementada em 2026-10-01 (334 testes ✅, drivers mockados); sem instância Oracle — validação manual pendente. Ver `features/F9_ORACLE_ADAPTER.md`.

> **Nota:** F9 e F10 do roadmap anterior (Version Management + Rollback Mechanism) foram removidos na revisão v1.8→v1.9 — como a plataforma não implementa Handlers, não há necessidade de versionamento de análises. O histórico de execuções (F8, já implementado) fornece auditoria suficiente para V1.0. Versionamento pode ser reintroduzido futuro (FB6/FB7) se a gestão de mudanças em análises se tornar crítica.

---

### Sprint 3: Production-Ready (≈ 2 semanas)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F12 | Autenticação e Controle de Acesso via Perfis | 🔴 Crítica | 3.5d | F5 | 🟩 Done (2026-09-30) |
| F13 | Docker Setup (Local + Remote) | 🔴 Crítica | 2d | F1-F8, F12 | 🟩 Done (2026-10-03) |
| F14 | Error Handling & Validation | 🟠 Alta | 1d | F4 | 🟩 Done (2026-10-03) |
| F15 | Performance Optimization | 🟠 Alta | 2d | F7 | 🟩 Done (2026-10-07) |
| F23 | API Admin: base + Usuários + Perfis (`/admin/users`, `/admin/profiles`, `/me`) | 🟠 Alta | 3.5d | F12 | 🟩 Done (2026-10-08; validação manual pendente: `features/F23_API_ADMIN_USUARIOS_PERFIS.md` §12) |
| F24 | API Admin: Data Sources + Analyses (`/admin/data-sources`, `/admin/analyses`) | 🟠 Alta | 3d | F23 | 🟩 Done (2026-10-08; validação manual pendente: `features/F24_API_ADMIN_DATA_SOURCES_ANALYSES.md` §12) |
| F25 | API Admin: Histórico de Execuções + estatísticas (`/admin/executions`) | 🟡 Média | 1.5d | F23 | 🟩 Done (2026-10-08) — `features/F25_API_ADMIN_HISTORICO_EXECUCOES.md` |
| F16 | API Documentation (MCP + Multi-Cliente) | 🟡 Média | 1d | F5, F23-F25 | ⬜ Todo |
| F17 | Unit Tests (80% coverage) | 🟠 Alta | ~1d (revisto; era 2d) | F1-F12 | 🟩 Done (2026-10-08) — `features/F17_UNIT_TESTS_COBERTURA.md` |
| F18 | Integration Tests (com múltiplos clientes MCP) | 🟡 Média | 1d | F6, F17 | ⬜ Todo |

**Total Sprint 3:** ~20.5 dias (12.5 + 8 da API administrativa F23–F25)

**F23–F25 em detalhe (API Administrativa) — resumo do escopo aprovado (plano completo com tabelas de endpoints em `~/.claude/plans/j-sei-que-tem-nested-milner.md`):**
```
Convenções: prefixo /admin, require_admin em todo router (as rotas ficam fora do AuthMiddleware,
que só cobre /mcp), paginação {items,total,limit,offset}, updated_at = NOW() em toda escrita,
e-mail normalizado, hash_password (bcrypt) novo, PostgreSQLAdapter.transaction(), CORS com PUT/PATCH.
Nunca devolver password_hash, token_hash ou connection_config.password.

F23 (base + Usuários + Perfis):
├─ users.is_admin (ALTER TABLE manual + schema.sql + seed_admin.sh) e require_admin
├─ /admin/users: listar/pesquisar, criar, detalhar, alterar, excluir (409 se há histórico),
│  redefinir senha (revoga tokens), block/unblock, vincular perfis, listar/revogar tokens
├─ /admin/profiles: listar/pesquisar, criar, detalhar, alterar, excluir (CASCADE),
│  vincular analyses e usuários
├─ /me (GET) e /me/password (PUT) — autosserviço de qualquer usuário autenticado
└─ Proteções: último admin ativo e o próprio admin não podem ser bloqueados/excluídos/rebaixados

F24 (Data Sources + Analyses) — spec: features/F24_API_ADMIN_DATA_SOURCES_ANALYSES.md (cache/invalidate = bump de updated_at; validate só estático; PATCH de conexão mesclado; teste de conexão salvo e prévio):
├─ /admin/data-sources: CRUD (valida chaves por type; cifra password com Fernet; nunca devolve),
│  test-connection, GET /types; editar/desativar invalida o pool em AnalysisService._adapters
└─ /admin/analyses: CRUD com analysis_steps e perfis em transação, validate_schema dos parâmetros,
   updated_at sempre atualizado (entra na chave do cache), validate, cache/invalidate

F25 (Histórico):
├─ GET /admin/executions (filtros analysis/user/status/error_code/cached/período; paginação; com parâmetros)
├─ GET /admin/executions/{id} e /stats; GET /admin/analyses/{id}/executions
└─ Índices compostos em execution_history só se o EXPLAIN justificar

Fora de escopo: tabela de auditoria das ações admin, rate limit/tentativas de senha (pré-requisito
antes de expor fora da rede interna), papéis granulares, retenção/purge, reset de senha por e-mail.
```

**F12 em detalhe (Autenticação e Controle de Acesso via Perfis):**
```
Objetivo: restringir list_tools()/call_tool() por usuário autenticado, sem
depender de OAuth2 nem JWT — ver ARQUITETURA.md ADR-007 para o racional
completo da escolha de token opaco.

Modelo de dados: usuário (N:N) perfil (N:N) analyses — um usuário só vê/executa
uma analysis se ela estiver ativa E vinculada a um perfil ativo vinculado a ele.

Escopo:
├─ Tabelas novas: users, profiles, user_profiles, profile_analyses, access_tokens
│  (ver DATABASE_SCHEMA.md §2.6-2.10 e ARQUITETURA.md §2.2)
├─ Token opaco (secrets.token_urlsafe(32)), hash SHA-256 persistido — nunca o
│  token bruto
├─ Emissão self-service: POST /auth/token (e-mail + senha, label e expire_days
│  opcionais) — rotas em routes/auth.py, registradas em main.py; senha guardada
│  como hash bcrypt em users.password_hash, e-mail em users.external_id
│  (sempre normalizado, minúsculas); usuário bloqueado/sem senha não gera token
├─ Revogação: POST /auth/revoke (e-mail + senha + token; credenciais validadas
│  antes do token; 404 se o token não existir ou for de outro usuário)
├─ N tokens por usuário, ilimitados (1 por cliente MCP, com `label` opcional)
├─ Expiração padrão 90 dias (ACCESS_TOKEN_EXPIRATION_DAYS), expire_days opcional
│  no request limitado por ACCESS_TOKEN_MAX_EXPIRATION_DAYS; renovação manual
│  pelo próprio usuário (novo POST /auth/token)
├─ Sem proteção contra tentativas de senha em V1.0 (só log) — rever antes de
│  expor fora da rede interna; usuários continuam cadastrados por INSERT direto
├─ list_tools() filtra analyses pela permissão efetiva do usuário autenticado
│  (JOIN profile_analyses + user_profiles, is_active em analyses E profiles)
├─ call_tool() revalida a permissão (não confia só no que list_tools() já mostrou)
├─ Usuário bloqueado (is_blocked=true) perde acesso imediatamente — checagem
│  sempre contra o BD, nunca contra claim armazenada no token
└─ execution_history ganha user_id (nullable) — quem executou cada análise

Sem JWT, sem OAuth2 — ver ADR-007 (ARQUITETURA.md §7)
para as 3 alternativas comparadas e por que token opaco venceu para este
projeto (multi-cliente heterogêneo, rede interna confiável, bloqueio precisa
ter efeito imediato). Spec completa: `features/F12_AUTENTICACAO_PERFIS.md`.
```

**F13 em detalhe (Docker Setup — um container por artefato) — ✅ implementada em 2026-10-03; abaixo o escopo original, ajustado: SQL Server e Oracle ficaram fora do compose (`docker/sqlserver/`, `docker/oracle/`); nginx + Certbot (profile opcional) entraram no remote; migration F12 cancelada:**
```
Objetivo: empacotar cada artefato do ambiente em seu próprio container, com
config por .env (RNF2 — zero mudança de código entre local e remoto).

Artefatos / containers (estado final — F13 implementada):
├─ app      → Dockerfile do servidor MCP (FastAPI, porta 3000, TLS via run_https.py)
│             inclui driver ODBC 18 (msodbcsql18, apt, antes do pip) para o SQL Server (F11);
│             Oracle (thin mode) e MySQL/PostgreSQL não exigem nada de SO
├─ postgres → container PostgreSQL (Config DB: src/database/schema.sql via initdb.d, já com as tabelas da F12)
└─ nginx    → só no remote (TLS terminado no nginx; certbot DNS-01 como profile opcional)
Opcionais, FORA dos compose (subida manual, um compose por banco em docker/<banco>/):
└─ mysql, sqlserver, oracle

Escopo transversal:
├─ docker-compose.local.yml (app + postgres) / docker-compose.remote.yml (nginx + app + postgres)
├─ .env.example (modelo do .env ÚNICO), .dockerignore, healthcheck em /health
├─ certs/ montado como volume (nunca dentro da imagem); secrets só via .env
└─ Autenticação já obrigatória (F12) — schema.sql (com as tabelas da F12) aplicado no init do container postgres

Resolvido na spec F13: SQL Server/MySQL/Oracle opcionais; nginx + Certbot (profile opcional); Redis fora do V1.0;
ODBC 18; seed do usuário admin no guia de deploy (F20).
Seed do admin (2026-10-04, pós-F14): src/database/seed_admin.sh roda sozinho na criação do banco (initdb.d, 02-seed-admin.sh)
nos compose local e dist — perfil "admin" + usuário (login admin, senha padrão CONHECIDA Senh@123, bcrypt via pgcrypto) +
vínculos, inclusive com todas as análises existentes; scripts/setup-admin.ps1 gera a FERNET_KEY no .env, sobe o compose,
reexecuta o seed (idempotente) e emite o token por POST /auth/token (secrets/admin-token.txt). O compose remote NÃO recebe
o seed (opt-in explícito; senha padrão conhecida não vai a um ambiente exposto por acidente).
```

**F14 em detalhe (Error Handling & Validation) — spec: `features/F14_ERROR_HANDLING_VALIDATION.md` (✅ implementada em 2026-10-03 — 480/480 testes; validação manual pendente, ver spec §6.2):**
```
Objetivo: erros com código estável para o LLM do cliente MCP, timeout distinto de
erro de conexão, retry só do que é transitório e contrato "nunca propaga exceção"
fechado — sem mudar success/volume_exceeded e sem isError do protocolo (contrato F5).

Escopo:
├─ Resposta de erro ganha error_code + retryable (ANALYSIS_NOT_FOUND — também para acesso negado, sem revelar que a análise existe,
│  INVALID_PARAMETERS, INVALID_ANALYSIS_CONFIG, DATA_SOURCE_UNAVAILABLE,
│  QUERY_TIMEOUT, QUERY_FAILED, INTERNAL_ERROR); tabela completa na spec §4.2
├─ execution_history.status passa a receber 'timeout'; coluna nova error_code VARCHAR(50)
│  (schema.sql; bancos existentes: ALTER TABLE execution_history ADD COLUMN error_code VARCHAR(50);)
├─ Retry (RNF4: 3x, backoff exponencial, QUERY_RETRY_* no .env) só em falha de
│  conexão; nunca em erro de SQL/validação; classificação por adapter
│  (is_timeout_error/is_transient_error), sem acoplar o service aos drivers
├─ call_tool()/list_tools() protegidos contra queda do Config DB; handler global do
│  FastAPI para /auth/* e /health (não cobre o /mcp, ver spec §4.4)
└─ Validação estrita de confirmar_volume_alto (string "false" não pode virar bypass)

Fora do escopo (pendências registradas): sslmode em PostgreSQL/MySQL (F11 #1) e
translate_params com ::nome/literais (F11 #5). Pontos em aberto na spec §11.
```

**F15 em detalhe (Performance Optimization) — spec: `features/F15_PERFORMANCE_OPTIMIZATION.md` (✅ implementada em 2026-10-07 — pool configurável + scripts; 500/500 testes; baseline, load test e revogação medidos no compose local; pendentes: bloqueio de usuário e EXPLAIN com volume realista, ver spec §12):**
```
Objetivo: medir antes de otimizar. Benchmark das metas de RNF1, pool PostgreSQL
configurável e otimização medida do Config DB, sem enfraquecer a F12.

Escopo:
├─ Pool PostgreSQL configurável (PG_POOL_MIN/MAX_SIZE; Config DB com par próprio);
│  padrão = comportamento atual (10) — resolve F11 #7 / F14 #4
├─ scripts/benchmark.py: cache hit <100ms, COUNT(*) <500ms, list_tools <2s,
│  análise leve <5s; baseline antes/depois (--compare); fora da suíte de testes
├─ Auth/permissões: só medir (EXPLAIN ANALYZE) e indexar se justificado — SEM cache de
│  token/permissão (bloqueio e revogação imediatos da F12 / ADR-007)
├─ Cache (F7) e touch_last_used: só medir; código só muda se o benchmark provar problema
└─ scripts/load_test.py: 10+ clientes simultâneos, manual, fora dos 480 testes

Fora do escopo: log assíncrono do execution_history (RNF4), sslmode (F11 #1),
translate_params (F11 #5) e análises assíncronas com status check. Pontos em aberto na spec §11.
```

---

### Sprint 4: Polish & Deploy (≈ 1 semana)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F19 | End-to-End Testing (Multi-Cliente) | 🟠 Alta | 1d | F18 | ⬜ Todo |
| F20 | Production Deployment Guide (Local + Remoto) | 🟠 Alta | 1d | F13 | ⬜ Todo |
| F21 | User Documentation (Setup por Cliente MCP) | 🟡 Média | 1d | F16 | ⬜ Todo |
| F22 | Demo & Training (com múltiplos clientes) | 🟡 Média | 1d | F19 | ⬜ Todo |

**Total Sprint 4:** ~4 dias

**Release:** V1.0 (MVP Local Multi-Cliente, com autenticação por token + perfis, com PostgreSQL + MySQL + SQL Server + Oracle)

**Total geral do projeto:** 22 features, ~31 dias (≈ 6 semanas com buffer normal de imprevistos — acrescida em +1 feature/+3.5d (2.5d na revisão v1.12, +1d na v1.14 pela emissão por e-mail/senha) pela adição de F12 "Autenticação e Controle de Acesso via Perfis" — ver nota de revisão no topo do documento).

---

## 2. Template de Especificação de Feature

Use este template para cada feature. **Copie e preencha**.

```markdown
# [F#] [Nome da Feature]

## Feature Spec Template

**ID:** F#
**Nome:** [Nome descritivo]
**Prioridade:** 🔴 Crítica / 🟠 Alta / 🟡 Média / 🟢 Baixa
**Esforço Estimado:** Xd (Xh)
**Status:** ⬜ Todo / 🟨 In Progress / 🟩 Done / 🟪 Blocked

---

## 1. Visão
[1-2 frases sobre o que a feature faz e por que é importante]

## 2. Objetivo
[O que você quer alcançar com essa feature?]

**Métrica de Sucesso:**
- ✅ Critério 1
- ✅ Critério 2

## 3. Contexto
**Depende de:** F# [Nome da feature anterior]
**É dependência de:** F# [Nome da feature que vem depois]

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
Componentes que serão criados/modificados:
├─ services/xxx_service.py (novo/modificado)
├─ repositories/xxx_repo.py (novo/modificado)
├─ schemas/xxx.py (novo/modificado)
└─ adapters/xxx_adapter.py (novo/modificado)
```

### 4.2 Fluxo de Dados
[Descreva o fluxo passo a passo. Use ASCII diagrams se necessário]

### 4.3 Banco de Dados
**Tabelas Novas / Modificações:**
```sql
CREATE TABLE xxx (...);
ALTER TABLE yyy ADD COLUMN zzz TYPE ...;
```

### 4.4 Endpoints/Interfaces
```python
async def xxx(self, param1: str, param2: int) -> XxxResult:
    """Descrição do que faz"""
    ...
```

## 5. Critérios de Aceitação
```gherkin
Feature: [Nome da Feature]

Scenario: [Caso de Uso 1]
  Given [Situação inicial]
  When [Ação]
  Then [Resultado esperado]

Scenario: [Caso de Erro]
  Given [Situação inicial]
  When [Ação que gera erro]
  Then [Erro tratado corretamente]
```

## 6. Testes

### 6.1 Testes Unitários
```python
class TestXxx:
    @pytest.mark.asyncio
    async def test_xxx_success(self):
        ...

    @pytest.mark.asyncio
    async def test_xxx_error_handling(self):
        ...
```

### 6.2 Checklist de Testes
- [ ] Teste unitário: caso de sucesso
- [ ] Teste unitário: validação de entrada
- [ ] Teste unitário: tratamento de erro
- [ ] Teste de integração: fluxo completo
- [ ] Manual: testar via pelo menos 1 cliente MCP real

## 7. Mudanças na Configuração
**Variáveis de Environment (.env):**
```
XXX_PARAM=value
```

## 8. Documentação
### 8.1 Como a feature aparece no MCP
### 8.2 Como o usuário usa essa feature
### 8.3 Como outros desenvolvedores estenderão isso

## 9. Checklist de Implementação
**Código:**
- [ ] Componentes implementados
- [ ] Code review completo
- [ ] Testes passing (100% dos casos)
- [ ] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] PR merge aprovado
```

---

## 3. Notas e Observações Gerais

- Todas as features de Sprint 1 compartilham o mesmo processo `uvicorn` — não há middleware de autenticação a considerar em nenhuma delas.
- F6 (validação multi-cliente) não é um serviço novo de código: é um passo de teste manual/integração que confirma que a arquitetura Streamable HTTP atende ao requisito de múltiplos clientes simultâneos.
- Autenticação (F12, retomando FB2/FB4 do Backlog Futuro — §9 abaixo) entrou no escopo desta versão, com um desenho revisado (perfis + token opaco) — ver nota de revisão v1.12 no topo do documento. `ClientIdentificationService` (FB1, qual cliente MCP/software está chamando — diferente de "qual usuário") segue fora de escopo, sem requisito de negócio que o justifique até agora.
- **Lições técnicas do protótipo F0** (`F0_PROTOTIPO_MCP_MEMORIA.md`), a considerar na implementação real de F1 para não serem redescobertas do zero: (1) TLS obrigatório mesmo em rede interna — clientes MCP reais recusam `http://` simples; (2) `mcp` precisa de teto de versão (`<2.0.0`) — a API de baixo nível usada no ADR-006 muda na v2.0.0; (3) a CLI do uvicorn não negocia ALPN, exigindo `ssl_context_factory` programático; (4) montar o endpoint MCP via `app.mount()` sem uma rota exata adicional gera redirect 307 em `/mcp` sem barra final; (5) CORS é necessário mesmo sem navegador tradicional envolvido, por conta de clientes desktop que validam o conector via `fetch()` no processo de renderer. Detalhes e evidências completas no README do protótipo (`mcp_prototype/README.md`).

---

## 4. Próximos Passos

### Antes de codar
```markdown
1. ✅ Revisar Documento de Negócio (NEGOCIO.md) — v1.7
2. ✅ Revisar Documento de Arquitetura (ARQUITETURA.md) — v1.12
3. ✅ Revisar este Roadmap (FEATURES_ROADMAP.md) — v1.9
4. ✅ Confirmar ambiente: Python 3.11, PostgreSQL acessível na rede local
```

### Sprint 1 — Ordem de Implementação
```markdown
1. ✅ F1: FastAPI + servidor MCP via Streamable HTTP rodando (porta 3000)
2. ✅ F2: PostgreSQL Adapter conectando ao BD de config
3. ✅ F3: Controle de Volume de Resultado (pré-checagem `COUNT(*)` + KB)
4. ✅ F4: Primeira análise executando de ponta a ponta
5. ✅ F5: list_tools() / call_tool() expostos via MCP
6. ✅ F6: Validado com 2+ clientes MCP diferentes simultaneamente (critérios 1–5)
7. ✅ F7: Cache in-memory funcionando
8. ✅ F8: Log de execução (analysis_id, params, status, tempo, cached flag)
```

### Sprint 3 — Estado atual (6/12 com F23–F25) e ordem sugerida do que resta (v1.22: inclui F23–F25, API administrativa, antes de F17/F16/F18)
```markdown
✅ F12: Autenticação e Controle de Acesso via Perfis
✅ F13: Docker Setup (Local + Remote)
✅ F14: Error Handling & Validation
✅ F15: Performance Optimization
⬜ Validações manuais pendentes de F13/F14/F15 (fluxo /auth/token → /mcp com cliente real,
   MySQL/SQL Server completos, SSE no nginx, Oracle 23ai, queda do Config DB, timeout de query,
   bloqueio de usuário, EXPLAIN com volume realista)
1. 🟩 F23: API Admin — base + Usuários + Perfis (feito 2026-10-08)
2. 🟩 F24: API Admin — Data Sources + Analyses (feito 2026-10-08)
3. ⬜ F25: API Admin — Histórico de Execuções (spec pendente)
4. ✅ F17: Unit Tests (80% coverage) — concluída 2026-10-08: suíte unitária sem banco, 99,97% (cobre também F23–F25)
5. ⬜ F16: API Documentation (MCP + Multi-Cliente) — inclui contrato de erro da F14, /auth/* e /admin/*
6. ⬜ F18: Integration Tests (múltiplos clientes MCP) — depende de F6 e F17
Depois: Sprint 4 (F19 → F20 → F21 → F22); F20 só depende de F13 e pode ser adiantada.
```

---

## 5. Workflow de Feature Development (SDD)

Para cada feature, siga este workflow:

```
1. Criar feature branch
   git checkout -b feature/F#-nome-feature

2. Preencher Feature Spec (usar o template da seção 2)

3. Implementar Feature
   - Seguir a especificação
   - Escrever testes simultaneamente
   - Código review

4. Testes
   - Unitários (80%+ coverage)
   - Integração
   - Manual (com pelo menos 1 cliente MCP real)

5. Documentação
   - README
   - Docstrings
   - API docs

6. Pull Request → Review → Merge (squash) → Atualizar status neste ROADMAP
```

---

## 6. Métricas de Sucesso do Projeto

| Métrica | Target | Status |
|---------|--------|--------|
| **Features Implementadas** | 25/25 | 15/25 🟩 |
| **Code Coverage** | 80%+ | 99,97% (suíte unitária sem banco, linhas+branches; F17, 2026-10-08) ✅ |
| **Análises Funcionando** | 5+ | 1+ ✅ |
| **Bancos de Dados Suportados** | 4 (PostgreSQL, MySQL, SQL Server, Oracle) | 4 (PostgreSQL, MySQL, SQL Server, Oracle) ✅ |
| **Clientes MCP testados simultaneamente** | 2+ (ex.: Claude Desktop + Gemini Desktop) | 2+ ✅ |
| **Tempo de Análise** | < 30s | < 5s ✅ |
| **Uptime Local** | 99%+ | TBD |
| **Agnóstico de Cliente** | 100% (MCP padrão via Streamable HTTP) | ✅ (validado F0 + F6) |
| **Documentação** | 100% | 100% (specs + ADRs) ✅ |

---

## 7. Timeline (Relativa ao Início da Implementação)

> Datas fixas foram removidas desta versão porque ficavam desatualizadas a cada revisão do escopo. Use dias relativos ao início real da Sprint 1.

```
Sprint 1 (Dias 1-10): MVP Local Multi-Cliente
├─ Dia 1-2:  F1 (FastAPI + MCP Streamable HTTP Setup)
├─ Dia 3-4:  F2 (PostgreSQL Adapter)
├─ Dia 5:    F3 (Controle de Volume de Resultado)
├─ Dia 6-7:  F4 (Execution Engine)
├─ Dia 8:    F5 (MCP Tools Integration)
├─ Dia 8.5:  F6 (Validação Multi-Cliente)
├─ Dia 9:    F7 (Cache Service)
└─ Dia 9.5:  F8 (Log de Execução)

Sprint 2 (Dias 10-14): Multi-DB
├─ Dia 10:    F10 (MySQL Adapter) ✅
├─ Dia 11-12: F11 (SQL Server Adapter) ✅
└─ Dia 13-14: F9  (Oracle Adapter) ✅

Sprint 3 (Dias 15-27): Production-Ready
├─ Dia 15-18: F12 (Autenticação e Controle de Acesso via Perfis) ✅
├─ Dia 19-20: F13 (Docker Local + Remote) ✅
├─ Dia 21:    F14 (Error Handling) ✅
├─ Dia 22-23: F15 (Performance) ✅
├─ Dia 24:    F16 (API Docs)
├─ Dia 25-26: F17 (Unit Tests)
└─ Dia 27:    F18 (Integration Tests)

Sprint 4 (Dias 27-30): Deploy
├─ Dia 27: F19 (E2E Testing)
├─ Dia 28: F20 (Deploy Guide)
├─ Dia 29: F21 (User Docs)
└─ Dia 30: F22 (Demo) → RELEASE V1.0
```

**Total:** ~31 dias úteis (≈ 6 semanas — dias acima são ilustrativos/arredondados, não uma soma exata)

---

## 8. Comunicação e Status

### Weekly Standup
```
☐ Seg — Planejar semana (quais features, quais bloqueadores)
☐ Qua — Mid-week check (progresso, algo bloqueado?)
☐ Sex — Retrospective (o que foi bem, o que melhorar)
```

### Status Updates
```
✅ DONE: F1 (FastAPI running)
🟨 IN PROGRESS: F2 (PostgreSQL adapter - 50%)
⬜ TODO: F3 (Controle de Volume)
🟪 BLOCKED: F4 (Waiting for F3)
```

---

## 9. Backlog Futuro (Fora do Escopo V1.0)

Quando a aplicação precisar sair da rede interna confiável (exposição remota) ou passar a suportar quotas por usuário, retomar:

```
FB1: ClientIdentificationService
├─ Propósito: rastrear qual cliente MCP/software está usando a plataforma
├─ Entrada: headers HTTP (User-Agent, client identifier)
└─ Armazena: tabela mcp_clients + execution_history.client_llm_name

FB3: Rate Limiting por Usuário
FB5: SSO/OAuth (Azure AD, Google, LDAP)
├─ Nota: avaliado como alternativa a F12 (ver ARQUITETURA.md ADR-007) e descartado
│  para V1.0 — clientes MCP heterogêneos (nem todo cliente implementa o fluxo de
│  autorização OAuth do MCP) e rede interna confiável não justificam a complexidade
│  de um authorization server. Pode voltar se a plataforma sair da rede confiável.

FB6: Analysis Version Management
├─ Propósito: rastrear histórico de mudanças em análises (comparar versões, diff, comentários)
└─ Nota: removido da Sprint 2 (v1.8→v1.9) pois não há Handlers — versionamento de dados
   é responsabilidade do LLM cliente, não do servidor

FB7: Analysis Rollback Mechanism
├─ Propósito: revert análise para versão anterior em 1 clique
└─ Nota: removido da Sprint 2 (v1.8→v1.9) — depende de FB6; sem Handlers, rollback
   é operação manual no BD até necessidade real aparecer
```

~~FB2: UserIdentificationService~~ e ~~FB4: RBAC (permissões por análise)~~ — implementadas nesta versão como **F12** (Autenticação e Controle de Acesso via Perfis), com um desenho revisado: perfis N:N (usuário↔perfil↔analyses) em vez de API Key direta + quota, e token opaco em vez de simplesmente "API Key" — ver ARQUITETURA.md ADR-007 e `features/F12_AUTENTICACAO_PERFIS.md`.

A especificação técnica completa (código de middleware, schema SQL, fluxos) que existia para FB1 fica preservada como referência para quando esse trabalho for retomado — não é necessário redesenhar do zero. FB6/FB7 (Version Management + Rollback) também podem ser reintroduzidas se a gestão de mudanças em análises se tornar crítica; a tabela `analysis_versions` foi removida do schema (ARQUITETURA.md v1.17) e voltaria via migration.

---

**Documento de Roadmap Completo — Multi-Cliente, Com Autenticação por Token + Perfis (F12), Sem Versionamento de Análises.**
**Sprint 1 (8/8) e Sprint 2 (3/3) concluídos. Sprint 3: F12 ✅, F13 ✅, F14 ✅ e F15 ✅ concluídas; próximas F16 (API Documentation), F17 e F18, depois Sprint 4 (Deploy).**
