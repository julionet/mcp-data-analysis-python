# 📦 Roadmap de Features e Template de Especificação

## Plataforma de Análise de Dados Genérica com MCP (Multi-Cliente, Streamable HTTP)

**Versão:** 1.11 (Aprovado — com PostgreSQL + MySQL (F10 ✅ Done) + SQL Server + Oracle, TLS obrigatório, **sem Handlers — servidor entrega dataset bruto**, sem Versionamento de Análises)
**Data:** 2026-09-28 (atualizado 2026-09-28 — F9 passa de MongoDB para Oracle)
**Status:** ✅ Aprovado
**Escopo:** Qualquer cliente MCP via Streamable HTTP **com TLS** (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.)

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
| F9 | Oracle Adapter (via `oracledb`, thin mode) | 🟡 Média | 1.5d | F2, F11 | ⬜ Todo |
| F10 | MySQL Adapter | 🟡 Média | 1d | F2 | 🟩 Done |
| F11 | SQL Server Adapter (via ODBC/`aioodbc`) | 🟡 Média | 1.5d | F2 | ⬜ Todo |

**Total Sprint 2:** ~3 dias (F10 concluído em 2026-09-27)

**Ordem de implementação:** F10 ✅ → F11 → F9 (o F9 reutiliza `tests/test_adapter_contract.py`, criado no F11).

**F11 em detalhe (SQL Server Adapter):** requer instalar o driver ODBC nativo da Microsoft (`msodbcsql17`/`18`) no ambiente/imagem Docker antes de usar `pyodbc`/`aioodbc` — isso é uma dependência de sistema operacional, não só de `pip install` (ver ARQUITETURA.md §5.1).

**F9 em detalhe (Oracle Adapter):** `python-oracledb` em modo thin (async nativo, sem Oracle Client no SO), Oracle Database 12.1+. Conexão por DSN montado a partir de `host`/`port`/`service_name` (ou `sid` para bancos antigos); parâmetros `:x` → `:pN` por índice de `param_names` (como o `$n` do PostgreSQL); chaves de coluna normalizadas para minúsculas; `SELECT 1 FROM DUAL` no `test_connection`. `sslmode`/TCPS fora do escopo. Sem instância Oracle no momento — validação manual pendente. Ver `features/F9_ORACLE_ADAPTER.md`.

> **Nota:** F9 e F10 do roadmap anterior (Version Management + Rollback Mechanism) foram removidos na revisão v1.8→v1.9 — como a plataforma não implementa Handlers, não há necessidade de versionamento de análises. O histórico de execuções (F8, já implementado) fornece auditoria suficiente para V1.0. Versionamento pode ser reintroduzido futuro (FB6/FB7) se a gestão de mudanças em análises se tornar crítica.

---

### Sprint 3: Production-Ready (≈ 2 semanas)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F12 | Docker Setup (Local + Remote) | 🔴 Crítica | 2d | F1-F8 | ⬜ Todo |
| F13 | Error Handling & Validation | 🟠 Alta | 1d | F4 | ⬜ Todo |
| F14 | Performance Optimization | 🟠 Alta | 2d | F7 | ⬜ Todo |
| F15 | API Documentation (MCP + Multi-Cliente) | 🟡 Média | 1d | F5 | ⬜ Todo |
| F16 | Unit Tests (80% coverage) | 🟠 Alta | 2d | F1-F11 | ⬜ Todo |
| F17 | Integration Tests (com múltiplos clientes MCP) | 🟡 Média | 1d | F6, F16 | ⬜ Todo |

**Total Sprint 3:** ~9 dias

---

### Sprint 4: Polish & Deploy (≈ 1 semana)

| # | Feature | Prioridade | Esforço | Depende de | Status |
|---|---------|-----------|--------|-----------|--------|
| F18 | End-to-End Testing (Multi-Cliente) | 🟠 Alta | 1d | F17 | ⬜ Todo |
| F19 | Production Deployment Guide (Local + Remoto) | 🟠 Alta | 1d | F12 | ⬜ Todo |
| F20 | User Documentation (Setup por Cliente MCP) | 🟡 Média | 1d | F15 | ⬜ Todo |
| F21 | Demo & Training (com múltiplos clientes) | 🟡 Média | 1d | F18 | ⬜ Todo |

**Total Sprint 4:** ~4 dias

**Release:** V1.0 (MVP Local Multi-Cliente, sem autenticação, com PostgreSQL + MySQL + SQL Server + Oracle)

**Total geral do projeto:** 21 features, ~27.5 dias (≈ 5.5 semanas com buffer normal de imprevistos — reduzido de 23 features/~30 dias na revisão v1.8 pela remoção de F9+F10 "Version Management + Rollback" (3d total): como não há Handlers, não há necessidade de versionamento de análises em V1.0. O histórico de execuções (F8) fornece auditoria suficiente — ver nota de revisão no topo do documento).

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
| **Features Implementadas** | 21/21 | 9/21 🟩 |
| **Code Coverage** | 80%+ | TBD |
| **Análises Funcionando** | 5+ | 1+ ✅ |
| **Bancos de Dados Suportados** | 4 (PostgreSQL, MySQL, SQL Server, Oracle) | 2 (PostgreSQL, MySQL) ✅ |
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
├─ Dia 11-12: F11 (SQL Server Adapter)
└─ Dia 13-14: F9  (Oracle Adapter)

Sprint 3 (Dias 15-24): Production-Ready
├─ Dia 15-16: F12 (Docker Local + Remote)
├─ Dia 17:    F13 (Error Handling)
├─ Dia 18-19: F14 (Performance)
├─ Dia 20:    F15 (API Docs)
├─ Dia 21-22: F16 (Unit Tests)
└─ Dia 23:    F17 (Integration Tests)

Sprint 4 (Dias 25-28): Deploy
├─ Dia 25: F18 (E2E Testing)
├─ Dia 26: F19 (Deploy Guide)
├─ Dia 27: F20 (User Docs)
└─ Dia 28: F21 (Demo) → RELEASE V1.0
```

**Total:** ~27.5 dias úteis (≈ 5.5 semanas — dias acima são ilustrativos/arredondados, não uma soma exata)

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

FB2: UserIdentificationService
├─ Propósito: rastrear qual pessoa está usando a plataforma, com quota
├─ Entrada: API Key por usuário (ex.: header Authorization: Bearer <token>)
└─ Armazena: tabelas users, user_api_keys + execution_history.user_id

FB3: Rate Limiting por Usuário
FB4: RBAC (permissões por análise)
FB5: SSO/OAuth (Azure AD, Google, LDAP)
FB6: Analysis Version Management
├─ Propósito: rastrear histórico de mudanças em análises (comparar versões, diff, comentários)
└─ Nota: removido da Sprint 2 (v1.8→v1.9) pois não há Handlers — versionamento de dados
   é responsabilidade do LLM cliente, não do servidor

FB7: Analysis Rollback Mechanism
├─ Propósito: revert análise para versão anterior em 1 clique
└─ Nota: removido da Sprint 2 (v1.8→v1.9) — depende de FB6; sem Handlers, rollback
   é operação manual no BD até necessidade real aparecer
```

A especificação técnica completa (código de middleware, schema SQL, fluxos) que existia para FB1/FB2 fica preservada como referência para quando esse trabalho for retomado — não é necessário redesenhar do zero. FB6/FB7 (Version Management + Rollback) também podem ser reintroduzidas se a gestão de mudanças em análises se tornar crítica; o schema `analysis_versions` já existe no BD para suportar isso futuro.

---

**Documento de Roadmap Completo — Multi-Cliente, Sem Autenticação em V1.0, Sem Versionamento de Análises.**
**Sprint 1 concluído (8/8 features). Próximas: Sprint 2 (Multi-DB) + Sprint 3/4 (Production + Deploy).**
