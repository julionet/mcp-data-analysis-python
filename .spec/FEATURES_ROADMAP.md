# 📦 Roadmap de Features e Template de Especificação

## Plataforma de Análise de Dados Genérica com MCP (Multi-Cliente, Streamable HTTP)

**Versão:** 1.5 (Aprovado — com PostgreSQL + MySQL + SQL Server + MongoDB, TLS obrigatório)
**Data:** 2026-09-23
**Status:** ✅ Aprovado
**Escopo:** Qualquer cliente MCP via Streamable HTTP **com TLS** (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.)

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
| F3 | HandlerRegistry e Discovery | 🔴 Crítica | 2d | F2 | ⬜ Todo |
| F4 | Analysis Execution Engine | 🔴 Crítica | 2d | F2, F3 | ⬜ Todo |
| F5 | MCP Tools Integration (`list_tools` / `call_tool`) | 🔴 Crítica | 1d | F1, F4 | ⬜ Todo |
| F6 | Validação Multi-Cliente Simultâneo | 🟠 Alta | 0.5d | F5 | ⬜ Todo |
| F7 | Cache Service (In-Memory) | 🟠 Alta | 1d | F4 | ⬜ Todo |
| F8 | Log de Execução (Simplificado) | 🟠 Alta | 0.5d | F4 | ⬜ Todo |

**Total Sprint 1:** ~11.5 dias (≈ 2 semanas com buffer)

**Destaque:**
- ✅ F1 + F5 garantem servidor MCP agnóstico de cliente, via Streamable HTTP com TLS
- ✅ F6 valida na prática que 2+ clientes MCP diferentes conseguem usar o servidor ao mesmo tempo
- ✅ F8 é um log simples (análise, parâmetros, status, tempo) — sem identificação de usuário/cliente

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

Nota: o protótipo F0 validou com sucesso um terceiro tipo de cliente MCP — o
Claude Code (CLI, via `claude mcp add --transport http`), além de Claude Desktop —
reforçando a evidência de "agnóstico de cliente" além de apps desktop.
```

---

### Sprint 2: Versioning & Multi-DB (≈ 1.5 semana)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F9 | Version Management | 🔴 Crítica | 2d | F4 | ⬜ Todo |
| F10 | Rollback Mechanism | 🟠 Alta | 1d | F9 | ⬜ Todo |
| F11 | MongoDB Adapter | 🟠 Alta | 1.5d | F2 | ⬜ Todo |
| F12 | MySQL Adapter | 🟡 Média | 1d | F2 | ⬜ Todo |
| F13 | SQL Server Adapter (via ODBC/`aioodbc`) | 🟡 Média | 1.5d | F2 | ⬜ Todo |
| F14 | Built-in Handlers (3x: aggregation, filtering, normalization) | 🟠 Alta | 2d | F3 | ⬜ Todo |

**Total Sprint 2:** ~9 dias

**F13 em detalhe (SQL Server Adapter):** requer instalar o driver ODBC nativo da Microsoft (`msodbcsql17`/`18`) no ambiente/imagem Docker antes de usar `pyodbc`/`aioodbc` — isso é uma dependência de sistema operacional, não só de `pip install` (ver ARQUITETURA.md §5.1).

---

### Sprint 3: Production-Ready (≈ 2 semanas)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F15 | Docker Setup (Local + Remote) | 🔴 Crítica | 2d | F1-F8 | ⬜ Todo |
| F16 | Error Handling & Validation | 🟠 Alta | 1d | F4 | ⬜ Todo |
| F17 | Performance Optimization | 🟠 Alta | 2d | F7 | ⬜ Todo |
| F18 | API Documentation (MCP + Multi-Cliente) | 🟡 Média | 1d | F5 | ⬜ Todo |
| F19 | Unit Tests (80% coverage) | 🟠 Alta | 2d | F1-F14 | ⬜ Todo |
| F20 | Integration Tests (com múltiplos clientes MCP) | 🟡 Média | 1d | F6, F19 | ⬜ Todo |

**Total Sprint 3:** ~9 dias

---

### Sprint 4: Polish & Deploy (≈ 1 semana)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F21 | End-to-End Testing (Multi-Cliente) | 🟠 Alta | 1d | F20 | ⬜ Todo |
| F22 | Production Deployment Guide (Local + Remoto) | 🟠 Alta | 1d | F15 | ⬜ Todo |
| F23 | User Documentation (Setup por Cliente MCP) | 🟡 Média | 1d | F18 | ⬜ Todo |
| F24 | Demo & Training (com múltiplos clientes) | 🟡 Média | 1d | F21 | ⬜ Todo |

**Total Sprint 4:** ~4 dias

**Release:** V1.0 (MVP Local Multi-Cliente, sem autenticação, com PostgreSQL + MySQL + SQL Server + MongoDB)

**Total geral do projeto:** 24 features, ~33 dias (≈ 6-7 semanas com buffer normal de imprevistos — número único, substitui as estimativas divergentes das versões anteriores deste documento, do EXECUTIVE_SUMMARY e do README, que foram descontinuados).

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
- Quando o requisito de autenticação voltar ao escopo (ver NEGOCIO.md §12 e ARQUITETURA.md §12), as features `ClientIdentificationService` e `UserIdentificationService` podem ser reintroduzidas aqui como novas entradas (numeração F24+, para não conflitar com o que já foi implementado).
- **Lições técnicas do protótipo F0** (`F0_PROTOTIPO_MCP_MEMORIA.md`), a considerar na implementação real de F1 para não serem redescobertas do zero: (1) TLS obrigatório mesmo em rede interna — clientes MCP reais recusam `http://` simples; (2) `mcp` precisa de teto de versão (`<2.0.0`) — a API de baixo nível usada no ADR-006 muda na v2.0.0; (3) a CLI do uvicorn não negocia ALPN, exigindo `ssl_context_factory` programático; (4) montar o endpoint MCP via `app.mount()` sem uma rota exata adicional gera redirect 307 em `/mcp` sem barra final; (5) CORS é necessário mesmo sem navegador tradicional envolvido, por conta de clientes desktop que validam o conector via `fetch()` no processo de renderer. Detalhes e evidências completas no README do protótipo (`mcp_prototype/README.md`).

---

## 4. Próximos Passos

### Antes de codar
```markdown
1. ✅ Revisar Documento de Negócio (NEGOCIO.md) — v1.2
2. ✅ Revisar Documento de Arquitetura (ARQUITETURA.md) — v1.2
3. ✅ Revisar este Roadmap (FEATURES_ROADMAP.md) — v1.2
4. ⬜ Confirmar ambiente: Python 3.11, PostgreSQL acessível na rede local
```

### Sprint 1 — Ordem de Implementação
```markdown
1. ✅ F1: FastAPI + servidor MCP via Streamable HTTP rodando (porta 3000)
2. ✅ F2: PostgreSQL Adapter conectando ao BD de config
3. ⬜ F3: Handler Registry descobrindo handlers (built-in + custom)
4. ⬜ F4: Primeira análise executando de ponta a ponta
5. ⬜ F5: list_tools() / call_tool() expostos via MCP
6. ⬜ F6: Validar com 2+ clientes MCP diferentes simultaneamente
7. ⬜ F7: Cache in-memory funcionando
8. ⬜ F8: Log de execução (analysis_id, params, status, tempo)
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
| **Features Implementadas** | 24/24 | 0/24 ⬜ |
| **Code Coverage** | 80%+ | TBD |
| **Análises Funcionando** | 5+ | 0 ⬜ |
| **Bancos de Dados Suportados** | 4 (PostgreSQL, MySQL, SQL Server, MongoDB) | 0 ⬜ |
| **Clientes MCP testados simultaneamente** | 2+ (ex.: Claude Desktop + Gemini Desktop) | 0 ⬜ |
| **Tempo de Análise** | < 30s | TBD |
| **Uptime Local** | 99%+ | TBD |
| **Agnóstico de Cliente** | 100% (MCP padrão via Streamable HTTP) | TBD |
| **Documentação** | 100% | 0% ⬜ |

---

## 7. Timeline (Relativa ao Início da Implementação)

> Datas fixas foram removidas desta versão porque ficavam desatualizadas a cada revisão do escopo. Use dias relativos ao início real da Sprint 1.

```
Sprint 1 (Dias 1-11): MVP Local Multi-Cliente
├─ Dia 1-2:  F1 (FastAPI + MCP Streamable HTTP Setup)
├─ Dia 3-4:  F2 (PostgreSQL Adapter)
├─ Dia 5-6:  F3 (Handler Registry)
├─ Dia 7-8:  F4 (Execution Engine)
├─ Dia 9:    F5 (MCP Tools Integration)
├─ Dia 9.5:  F6 (Validação Multi-Cliente)
├─ Dia 10:   F7 (Cache Service)
└─ Dia 10.5: F8 (Log de Execução)

Sprint 2 (Dias 12-21): Versioning + Multi-DB
├─ Dia 12-13: F9  (Version Management)
├─ Dia 14:    F10 (Rollback)
├─ Dia 15-16: F11 (MongoDB Adapter)
├─ Dia 17:    F12 (MySQL Adapter)
├─ Dia 18-19: F13 (SQL Server Adapter)
└─ Dia 20-21: F14 (Built-in Handlers)

Sprint 3 (Dias 22-30): Production-Ready
├─ Dia 22-23: F15 (Docker Local + Remote)
├─ Dia 24:    F16 (Error Handling)
├─ Dia 25-26: F17 (Performance)
├─ Dia 27:    F18 (API Docs)
├─ Dia 28-29: F19 (Unit Tests)
└─ Dia 30:    F20 (Integration Tests)

Sprint 4 (Dias 31-34): Deploy
├─ Dia 31: F21 (E2E Testing)
├─ Dia 32: F22 (Deploy Guide)
├─ Dia 33: F23 (User Docs)
└─ Dia 34: F24 (Demo) → RELEASE V1.0
```

**Total:** ~33 dias úteis (≈ 6-7 semanas — dias acima são ilustrativos/arredondados, não uma soma exata)

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
⬜ TODO: F3 (Handler registry)
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

FB2: UserIdentificationService
├─ Propósito: rastrear qual pessoa está usando a plataforma, com quota
├─ Entrada: API Key por usuário (ex.: header Authorization: Bearer <token>)
└─ Armazena: tabelas users, user_api_keys + execution_history.user_id

FB3: Rate Limiting por Usuário
FB4: RBAC (permissões por análise)
FB5: SSO/OAuth (Azure AD, Google, LDAP)
```

A especificação técnica completa (código de middleware, schema SQL, fluxos) que existia para FB1/FB2 fica preservada como referência para quando esse trabalho for retomado — não é necessário redesenhar do zero.

---

**Documento de Roadmap Completo — Multi-Cliente, Sem Autenticação em V1.0.**
**Pronto para iniciar desenvolvimento seguindo SDD, começando por F1.**
