# CLAUDE.md

# Análise de Dados Genérica com MCP - V1.0

## Projeto
Plataforma agnóstica de LLM para análise de dados conversacional, **multi-cliente MCP** (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc. — todos via Streamable HTTP), multi-database, com versionamento. **Sem autenticação/identificação de usuário ou cliente em V1.0** (rede interna confiável).

## Stack
FastAPI + MCP (Streamable HTTP, endpoint único `/mcp`, porta 3000) + PostgreSQL + Python. Cache em memória local (Redis só em ambiente remoto/futuro).

## Foco Atual (Sprint 1 — ~11 dias)
- F1: FastAPI + MCP Server via Streamable HTTP
- F2: PostgreSQL Adapter
- F3: HandlerRegistry e Discovery
- F4: Analysis Execution Engine
- F5: MCP Tools Integration (`list_tools`/`call_tool`)
- F6: Validação Multi-Cliente Simultâneo (2+ clientes MCP diferentes)
- F7: Cache Service (in-memory)
- F8: Log de Execução (simplificado, sem identificação de usuário/cliente)

## Documentos (v1.4 — Aprovados)
- **NEGOCIO.md**: Requisitos (RF1-RF5, T1-T5, RNF1-RNF5)
- **ARQUITETURA.md**: Design técnico (componentes, schema, ADRs, fluxos)
- **FEATURES_ROADMAP.md**: Timeline (24 features, ~33 dias, Sprint 1-4)
- **TEMPLATE_FEATURE_SPEC.md**: Template (modelo de spec de features)

> `IDENTIFICATION_SERVICES_V1_0.md`, `EXECUTIVE_SUMMARY_V1_0.md`, `README_V1_0.md` e `MANIFEST_V1_0.md` foram descontinuados — a spec de autenticação multi-user saiu do escopo de V1.0 e ficou preservada como "Backlog Futuro" dentro dos 3 documentos acima.

## Requisitos V1.0
✅ Multi-cliente MCP simultâneo, via Streamable HTTP, sem autenticação
✅ 4 bancos de dados suportados: PostgreSQL, MySQL, SQL Server, MongoDB
✅ Versionamento de análises + rollback
✅ Handlers Python customizáveis (discovery dinâmico)
✅ Log de execução simples (análise, parâmetros, status, tempo — sem identificar quem/qual cliente)
❌ Sem API Key, sem quota por usuário, sem RBAC (fora de escopo V1.0 — ver Roadmap Futuro)

## Como Ajudar
1. Especificação/design técnico → Cite **ARQUITETURA.md**
2. Cronograma/ordem de features → Cite **FEATURES_ROADMAP.md**
3. Requisitos/critérios de aceitação → Cite **NEGOCIO.md**
4. Template de spec para features - Use **TEMPLATE_FEATURE_SPEC.md**
5. Código → só depois da spec da feature ser confirmada; apresentar para execução manual, nunca gerar tudo de uma vez
6. **Regra de ouro:** nunca inventar — perguntar sempre que houver ambiguidade ou decisão de arquitetura em aberto

## Estilo
Direto, técnico, com código-exemplo, sempre referenciando o documento. Português. Próximos passos claros.
