# CLAUDE.md

# Análise de Dados Genérica com MCP - V1.0

## Projeto
Plataforma agnóstica de LLM para análise de dados conversacional, **multi-cliente MCP** (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc. — todos via Streamable HTTP com TLS obrigatório), multi-database. **Sem autenticação/identificação de usuário ou cliente em V1.0** (rede interna confiável). **Servidor não transforma dados** (sem handlers) — executa a query parametrizada e devolve o dataset bruto; é o LLM do cliente MCP quem interpreta/agrega, com um Controle de Volume (COUNT(*) + KB) protegendo contra resultados grandes demais. Log de execução completo para auditoria (sem identificação de usuário/cliente).

## Stack
FastAPI + MCP (Streamable HTTP com TLS obrigatório, endpoint único `/mcp`, porta 3000) + PostgreSQL + Python. Cache em memória local (Redis só em ambiente remoto/futuro).

## Status Atual (Sprint 1 — ✅ 100% Completo | Sprint 2 — 🟨 Em Progresso)

### Sprint 1: MVP Local Multi-Cliente (✅ 100%)
- F1: FastAPI + MCP Server via Streamable HTTP com TLS 🟩 Done
- F2: PostgreSQL Adapter 🟩 Done
- F3: Controle de Volume de Resultado (pré-checagem COUNT(*) + KB, recusa com refinamento) 🟩 Done
- F4: Analysis Execution Engine 🟩 Done
- F5: MCP Tools Integration (`list_tools`/`call_tool`) 🟩 Done
- F6: Validação Multi-Cliente Simultâneo (2+ clientes MCP, critérios 1–5 incluindo execution_history sem erro) 🟩 Done
- F7: Cache Service (in-memory) 🟩 Done
- F8: Log de Execução (analysis_id, params, status, time, rows, size, cached flag — sem identificação de usuário) 🟩 Done

### Sprint 2: Multi-DB Adapters (1/3 concluído)
- F9: Oracle Adapter ⬜ Todo (implementar após F11)
- F10: MySQL Adapter 🟩 Done (named parameters `%(name)s`, 3 correções, 23/23 testes ✅)
- F11: SQL Server Adapter ⬜ Todo

## Documentos (Aprovados e Atualizados)
- **NEGOCIO.md** (v1.8): Requisitos (RF1-RF3, T1-T5, RNF1-RNF5) — versionamento removido
- **ARQUITETURA.md** (v1.15): Design técnico (componentes, schema, ADRs, fluxos) — VersionService/Repository removidas
- **FEATURES_ROADMAP.md** (v1.11): Timeline (21 features, ~27.5 dias, Sprint 1-4) — F9/F10 removidas, F11-F23 renumeradas → F9-F21
- **TEMPLATE_FEATURE_SPEC.md**: Template (modelo de spec de features)
- **PROPOSTA_REVISAO_HANDLERS_E_VOLUME.md**: racional da remoção de Handlers e Controle de Volume

> `IDENTIFICATION_SERVICES_V1_0.md`, `EXECUTIVE_SUMMARY_V1_0.md`, `README_V1_0.md` e `MANIFEST_V1_0.md` foram descontinuados — a spec de autenticação multi-user saiu do escopo de V1.0 e ficou preservada como "Backlog Futuro" dentro dos 3 documentos acima.

## Requisitos V1.0 (Sprint 1 — Concluído | Sprint 2 — Em Progresso)
✅ Multi-cliente MCP simultâneo, via Streamable HTTP com TLS obrigatório, sem autenticação
✅ PostgreSQL Adapter (completo com DML: INSERT/UPDATE/DELETE)
✅ MySQL Adapter (F10, com tradução agnóstica de placeholders — `:param` → `%(param)s`)
🟨 SQL Server e Oracle Adapters em progresso (Sprint 2)
✅ Servidor entrega dataset bruto (sem handlers); Controle de Volume recusa/pede refinamento se exceder limites (.env)
✅ Log de execução completo (analysis_id, params, status, execution_time_ms, rows_affected, result_size_bytes, cached flag — sem identificar usuário/cliente)
✅ Cache in-memory com TTL configurável por análise
✅ 2+ clientes MCP simultâneos validados (execution_history sem erro de concorrência)
✅ Placeholders agnósticos de banco — SQL com `:param` é traduzido por adapter (PostgreSQL `$n`, MySQL `%(n)s`, SQL Server `@n`→`?`, Oracle `:pN`); o dialeto SQL não é traduzido — para rodar nos 4 bancos usar o subconjunto comum (sem `ORDER BY`/CTE/`;` no topo, colunas com nome único, todo parâmetro declarado presente no SQL — ver F11 §8.4 e F9 §8.4)
❌ Sem API Key, sem quota por usuário, sem RBAC (fora de escopo V1.0 — ver Roadmap Futuro)
❌ Sem versionamento de análises/rollback (removido: query SQL é configurada 1 vez; mudanças são diretas na tabela — histórico de execuções fornece auditoria necessária)

## Como Ajudar
1. Especificação/design técnico → Cite **ARQUITETURA.md**
2. Cronograma/ordem de features → Cite **FEATURES_ROADMAP.md**
3. Requisitos/critérios de aceitação → Cite **NEGOCIO.md**
4. Template de spec para features - Use **TEMPLATE_FEATURE_SPEC.md**
5. Código → só depois da spec da feature ser confirmada; apresentar para execução manual, nunca gerar tudo de uma vez
6. **Regra de ouro:** nunca inventar — perguntar sempre que houver ambiguidade ou decisão de arquitetura em aberto

## Estilo
Direto, técnico, com código-exemplo, sempre referenciando o documento. Português. Próximos passos claros.
