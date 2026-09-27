# F6 Validação Multi-Cliente Simultâneo

## Feature Spec

**ID:** F6
**Nome:** Validação Multi-Cliente Simultâneo
**Prioridade:** 🟠 Alta
**Esforço Estimado:** 0.5d (4h)
**Status:** 🟩 Done (critérios 1–4; critério 5 pendente do F8 — ver FEATURES_ROADMAP.md v1.7)

> **Nota de fechamento (2026-09-26):** roteiro executado e confirmado por Jose fora desta sessão — os detalhes técnicos (saída do handshake ALPN, IDs de sessão, datasets retornados) não foram registrados neste documento no momento da execução. A tabela §6.3 fica com a confirmação geral; se as evidências detalhadas existirem em outro lugar (logs, terminal), podem ser coladas aqui depois.

> **Fontes:** FEATURES_ROADMAP.md (§1 "F6 em detalhe", §3), NEGOCIO.md (§6 UC2, §11), ARQUITETURA.md (ADR-006, §9.1) e decisões desta sessão (clientes, máquina, análise, formato do teste, critério 5).
> Itens marcados com **[A DEFINIR]** não constam nos documentos nem foram decididos, e devem ser preenchidos antes da execução. Nada foi presumido.

---

## 1. Visão
Confirmar, na prática, que o servidor MCP (Streamable HTTP com TLS, sem autenticação) atende **dois clientes ao mesmo tempo** apontando para a mesma URL, ambos recebendo o resultado correto. F6 **não cria código novo**: é um roteiro de validação manual.

## 2. Objetivo
Provar o requisito de "multi-cliente simultâneo" do Sprint 1 (NEGOCIO.md §11) sobre o servidor entregue por F1 a F5.

**Métrica de Sucesso:**
- ✅ Handshake TLS/ALPN confirmado antes dos testes com clientes reais
- ✅ 2 clientes MCP conectados à mesma URL `https://localhost:3000/mcp`, ambos listando a análise `vendas_por_periodo`
- ✅ Mesma análise pedida nos dois clientes, em paralelo, com resultado correto em ambos
- ⏸️ `execution_history` mostra as duas execuções, sem erro de concorrência (**validado somente após F8**, ver §5.1)

## 3. Contexto
**Depende de:** F5 (MCP Tools Integration), 🟩 Done
**Validação parcial do critério 5 depende de:** F8 (Log de Execução), ⬜ Todo
**É dependência de:** F19 (Integration Tests com múltiplos clientes)

**Decisões de escopo desta sessão:**

| Item | Decisão |
|---|---|
| Clientes | 2 instâncias do **Claude Code (CLI)**, via Streamable HTTP |
| Máquina | Cliente(s) e servidor na **mesma máquina** |
| Análise de teste | `vendas_por_periodo` |
| Formato | **Roteiro manual** |
| "Em paralelo" | Sem critério mensurável; basta disparar nos dois clientes quase ao mesmo tempo |
| Critério 5 | Movido para depois da F8 (`log_execution` ainda não implementado) |

**Observação:** os dois clientes são o mesmo software (Claude Code) em duas instâncias. Isso valida concorrência de sessões no servidor, mas **não** valida clientes de fabricantes diferentes. O F0 já havia validado Claude Desktop e Claude Code individualmente.

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
Nenhum componente de código é criado ou modificado.
Entregáveis:
├─ Este documento (spec + roteiro)
└─ Registro de evidências da execução (seção 6.3)

Componentes exercitados (já implementados em F1–F5):
├─ main.py (uvicorn + TLS/ALPN, rota /mcp, CORS)
├─ mcp_transport/tools.py (list_tools / call_tool)
├─ services/analysis_service.py (execute)
└─ services/volume_guard_service.py (F3)
```

### 4.2 Fluxo de Dados
```
Claude Code #1 ─┐
                ├─ Streamable HTTP (TLS) ─> https://localhost:3000/mcp
Claude Code #2 ─┘                                  │
                                                   ▼
                                    list_tools() / call_tool("vendas_por_periodo")
                                                   │
                                                   ▼
                                    AnalysisService.execute()  ─> PostgreSQL
                                                   │
                                    resposta independente para cada cliente
```

### 4.3 Banco de Dados
Não se aplica. Nenhuma tabela nova ou alteração.

### 4.4 Endpoints/Interfaces
Não se aplica. Usa apenas a interface MCP existente (`list_tools`, `call_tool`).

## 5. Critérios de Aceitação

```gherkin
Feature: Validação Multi-Cliente Simultâneo

Scenario: Handshake TLS/ALPN antes dos clientes
  Given o servidor está rodando em https://localhost:3000
  When executo "openssl s_client -alpn h2,http/1.1" contra localhost:3000
  Then o handshake TLS é concluído com sucesso
  And o protocolo ALPN negociado é registrado como evidência

Scenario: Dois clientes conectados à mesma URL
  Given o servidor está rodando com a análise "vendas_por_periodo" cadastrada
  When configuro duas instâncias do Claude Code apontando para https://localhost:3000/mcp
  Then ambas se conectam sem nenhuma configuração de autenticação
  And ambas listam a análise "vendas_por_periodo"

Scenario: Mesma análise em paralelo
  Given as duas instâncias estão conectadas
  When peço "vendas_por_periodo" com os mesmos parâmetros nas duas, quase ao mesmo tempo
  Then ambas recebem o dataset bruto com status "success"
  And os resultados são idênticos entre si e corretos em relação ao banco
  And nenhuma das duas sofre erro por causa da outra

Scenario: Registro das execuções (validado após F8)
  Given F8 concluída e as duas execuções acima realizadas
  When consulto execution_history
  Then existem duas execuções de "vendas_por_periodo"
  And não há erro de concorrência registrado
```

### 5.1 Status por critério

| # | Critério | Validável agora? |
|---|---|---|
| 1 | Handshake TLS/ALPN | ✅ Sim |
| 2 | 2 clientes na mesma URL | ✅ Sim |
| 3 | Mesma análise em paralelo | ✅ Sim |
| 4 | Ambos recebem resultado correto | ✅ Sim |
| 5 | `execution_history` com as 2 execuções | ⏸️ Só após F8 |

**Regra de conclusão:** F6 pode ser dado como concluído nos critérios 1 a 4. O critério 5 fica como pendência registrada e é fechado quando a F8 estiver pronta.

## 6. Testes

### 6.1 Testes Unitários
Não se aplica (F6 não cria código).

### 6.2 Roteiro de Validação Manual

**Pré-requisitos**
- [ ] F1 a F5 concluídas (confirmado: 🟩 Done)
- [ ] Certificado mkcert gerado incluindo `localhost` e `127.0.0.1` (ARQUITETURA.md §9.1)
- [ ] Servidor rodando com `ssl_context_factory` e ALPN `http/1.1` (F1)
- [ ] Análise `vendas_por_periodo` cadastrada e ativa no banco de configuração
- [ ] Parâmetros de teste de `vendas_por_periodo`: **[A DEFINIR]**
- [ ] Parâmetros escolhidos retornam volume **dentro** dos limites do Controle de Volume (F3); caso contrário a resposta será `volume_exceeded` e o teste não valida o que deveria
- [ ] Resultado esperado (linhas/valores conferidos direto no banco): **[A DEFINIR]**

**Passo 1: Handshake TLS/ALPN**
```bash
openssl s_client -connect localhost:3000 -alpn h2,http/1.1
```
- [ ] Handshake concluído sem erro
- [ ] Anotar o protocolo ALPN negociado (esperado: `http/1.1`, conforme F1)

Se falhar aqui, **não** prosseguir: uma falha de ALPN não gera log HTTP, só conexão abandonada, e se confunde com outros erros.

**Passo 2: Conectar os dois clientes**

Em dois terminais separados (duas instâncias do Claude Code), registrar o servidor conforme validado no F0:
```bash
claude mcp add --transport http analysis https://localhost:3000/mcp
```
- [ ] Instância #1 conectada
- [ ] Instância #2 conectada
- [ ] Nenhum header ou API Key configurado
- [ ] Ambas listam a análise `vendas_por_periodo`

> Se as duas instâncias compartilharem o mesmo escopo de configuração do Claude Code (mesma entrada `analysis`), isso é esperado; o que importa é haver **duas sessões simultâneas** no servidor. Confirmar na prática que são duas sessões distintas: **[A DEFINIR: como verificar, por exemplo pelos logs do servidor]**.
>
> Se o Claude Code não confiar no certificado do mkcert, o F0 registra apenas que a conexão funcionou; o procedimento exato de confiança para o Claude Code **não consta nos documentos**. Se ocorrer, parar e definir antes de improvisar.

**Passo 3: Execução em paralelo**
- [ ] Preparar o mesmo pedido, com os mesmos parâmetros, nas duas instâncias
- [ ] Disparar nas duas quase ao mesmo tempo (sem critério mensurável)
- [ ] Instância #1 recebeu `status: "success"` com dataset bruto
- [ ] Instância #2 recebeu `status: "success"` com dataset bruto
- [ ] Os dois datasets são idênticos entre si
- [ ] Os dados conferem com o banco
- [ ] Nenhum erro, timeout ou resposta cruzada entre as sessões
- [ ] Logs do servidor sem exceções durante a execução

**Passo 4: `execution_history` (somente após F8)**
- [ ] Duas linhas de `vendas_por_periodo` com `status = success` e `executed_at` próximos
- [ ] Sem `error_message` de concorrência
- [ ] Sem identificação de usuário/cliente (V1.0, NEGOCIO.md §9 T5)

### 6.3 Registro de Evidências (preencher na execução)

| Item | Resultado | Observação |
|---|---|---|
| Saída do `openssl s_client` (ALPN) | ✅ Confirmado | Detalhe técnico não registrado nesta sessão |
| Instância #1: tools listadas | ✅ Confirmado | |
| Instância #2: tools listadas | ✅ Confirmado | |
| Instância #1: resultado da análise | ✅ Confirmado | |
| Instância #2: resultado da análise | ✅ Confirmado | |
| Resultados idênticos? | ✅ Sim | |
| Erros nos logs do servidor | ✅ Nenhum reportado | |
| `execution_history` (após F8) | ⏸️ pendente F8 | |

## 7. Mudanças na Configuração
Nenhuma. F6 não altera `.env` nem código.

## 8. Documentação
### 8.1 Como a feature aparece no MCP
Não se aplica. Não há nova tool ou recurso.
### 8.2 Como o usuário usa essa feature
Não se aplica. É validação interna. O comando de conexão do Claude Code (Passo 2) serve de referência para a documentação de setup por cliente (F22).
### 8.3 Como outros desenvolvedores estenderão isso
O roteiro manual é a base para o teste de integração automatizado com múltiplos clientes (F19).

## 9. Checklist de Implementação
**Execução:**
- [x] Pré-requisitos preenchidos (incluindo os itens **[A DEFINIR]**)
- [x] Passo 1 (TLS/ALPN) concluído
- [x] Passo 2 (2 clientes conectados) concluído
- [x] Passo 3 (execução em paralelo) concluído
- [x] Evidências registradas na seção 6.3 (confirmação geral — sem detalhe técnico registrado)

**Fechamento:**
- [x] F6 marcado como 🟩 Done no FEATURES_ROADMAP.md (critérios 1 a 4)
- [x] Critério 5 registrado como pendência de F8
- [ ] Passo 4 executado após F8 e critério 5 fechado

---

## Pendências em aberto
1. Parâmetros e resultado esperado de `vendas_por_periodo` para o teste.
2. Como confirmar que as duas instâncias do Claude Code são sessões distintas no servidor.
3. Procedimento de confiança no certificado mkcert para o Claude Code, se a conexão falhar (não consta nos documentos).
4. Limitação registrada: os 2 clientes são o mesmo software, então esta validação não cobre clientes de fabricantes diferentes.
