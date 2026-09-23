# 📋 Documento de Negócio

## Plataforma de Análise de Dados Genérica com MCP

**Versão:** 1.5 (Aprovado — Streamable HTTP **com TLS obrigatório** Multi-Cliente, sem autenticação em V1.0, com PostgreSQL + MySQL + SQL Server + MongoDB)
**Data:** 2026-09-23
**Autor:** Jose
**Status:** ✅ Aprovado

> **Nota de revisão (v1.1 → v1.2):** a versão anterior deste documento (23/09) incluía RF6 e T5 (autenticação multi-user via API Key). Após revisão, ficou definido que **V1.0 roda em rede interna confiável, sem identificação de usuário ou de cliente MCP**. Esses requisitos foram removidos daqui e movidos para "Roadmap Futuro" (seção 12), para quando a aplicação precisar sair da rede confiável.

> **Nota de revisão (v1.2 → v1.3):** documento aprovado. Adicionado suporte a **SQL Server** como banco de dados de origem de primeira classe em V1.0 (RF5, seção 10), ao lado de PostgreSQL, MySQL e MongoDB.

> **Nota de revisão (v1.3 → v1.4):** documento aprovado. Trocado o transporte MCP de **HTTP+SSE** para **Streamable HTTP** — o transporte mais recente da especificação MCP, que substitui o antigo transporte HTTP+SSE. Mantém a mesma topologia (serviço único, porta 3000, múltiplos clientes MCP simultâneos, sem autenticação em V1.0), mudando apenas o protocolo de transporte e o path do endpoint (de `/sse` para `/mcp`). Ver Restrição T4 (seção 9) e ARQUITETURA.md §7 ADR-006 para detalhes técnicos.

> **Nota de revisão (v1.4 → v1.5):** documento aprovado. O protótipo F0 (`F0_PROTOTIPO_MCP_MEMORIA.md`) revelou que **TLS (HTTPS) é obrigatório mesmo em V1.0, mesmo em rede interna confiável** — não por política de segurança da arquitetura, mas porque clientes MCP reais (confirmado: Claude Desktop) recusam se conectar a um conector remoto via `http://` simples, independente da rede ser confiável ou não. Isso muda a Restrição T1 e a T4 (seção 9), a RNF5 (seção 8) e a lista de dependências externas (seção 10), que passam a exigir um certificado TLS (self-signed local via mkcert para desenvolvimento, ou CA interna quando o servidor precisar ser acessado por mais de uma máquina). Ver ARQUITETURA.md §7 ADR-006 e §9 para a estratégia de certificado.

---

## 1. Visão do Produto

Uma **plataforma de análise de dados genérica e agnóstica** que permite a qualquer usuário realizar análises complexas contra múltiplos bancos de dados através de uma interface conversacional com **qualquer LLM que implemente MCP** (Claude Desktop, Gemini Desktop, OpenAI Desktop, e futuros), sem necessidade de escrever código Python para cada nova análise.

O servidor roda como um **serviço Streamable HTTP único na rede interna**, e múltiplos usuários — cada um com o cliente MCP de sua preferência — podem se conectar a ele simultaneamente, sem necessidade de configuração individual de autenticação em V1.0.

**Escopo de Clientes MCP Suportados (V1.0):**
- ✅ Qualquer cliente MCP compatível com o protocolo padrão via Streamable HTTP (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.), conectando à mesma instância do servidor na rede local.

**Escopo Futuro:**
- 🔄 Exposição remota (fora da rede confiável) — exige reintrodução de autenticação (ver seção 12).
- 🔄 Clientes LLM baseados em API (sem app desktop) via gateway MCP.

---

## 2. Problema

### Situação Atual (As-Is)

```
Análise de dados hoje:
├─ Escrever SQL manualmente
├─ Executar manualmente no cliente DB
├─ Processar dados em Python/Pandas
├─ Enviar resultado para o LLM manualmente
└─ Repetir para cada análise nova
```

**Dor:**
- ⏱️ Demorado (30min-1h por análise)
- 🔁 Repetitivo (mesmo padrão todo mês)
- 👨‍💻 Requer código (SQL + Python skills)
- 📦 Difícil de versionar e auditar
- 🔄 Impossível fazer análises ad-hoc conversacionais

### Situação Desejada (To-Be)

```
Com a plataforma:
├─ Configurar análise 1 vez no BD (INSERT SQL)
├─ Qualquer cliente MCP descobre automaticamente
├─ Pedir análise em linguagem natural (com o LLM de preferência)
├─ Sistema conecta ao BD certo, executa, retorna
└─ Reutilizar infinitamente (zero código novo)
   └─ Independente de qual cliente MCP o usuário está usando
```

**Benefício:**
- ⚡ Instantâneo (segundos vs horas)
- 🎯 Precisão (regras em BD, não em código)
- 📊 Análises ad-hoc conversacionais
- 📝 Histórico de execuções (análise, parâmetros, resultado)
- 🔄 Reutilizável infinitamente

---

## 3. Objetivos de Negócio

### Objetivo Principal (O1)
**Eliminar o ciclo manual de análise de dados**

```
Métrica de Sucesso:
├─ Tempo médio da análise: < 30s (vs 30min hoje)
├─ Análises reutilizáveis: 100% (vs 0% hoje)
└─ Código novo por mês: 0 (vs 500+ linhas Python)
```

### Objetivo Secundário (O2)
**Capacitar qualquer cliente MCP como assistente de análise conversacional**

```
Métrica de Sucesso:
├─ Taxa de acerto de análises: > 95% (independente do cliente)
├─ Adaptabilidade: suportar qualquer BD (PostgreSQL, MongoDB, API, etc)
├─ Agnóstico de cliente: funcionar com qualquer app MCP via Streamable HTTP
├─ Multi-cliente simultâneo: 2+ clientes MCP diferentes conectados à mesma instância
└─ Escalabilidade: suportar transição local → remoto sem mudanças de código
```

### Objetivo Terciário (O3)
**Manter histórico completo de execuções (o quê, quando, com que resultado)**

```
Métrica de Sucesso:
├─ Histórico: 100% das análises versionadas
├─ Log de execução: 100% das execuções registradas (análise, parâmetros, status, tempo)
└─ Rollback: voltar para versão anterior em segundos

Nota: em V1.0 o log de execução NÃO identifica usuário nem cliente MCP
(ver seção 9, Restrição T5, e seção 12, Roadmap Futuro).
```

---

## 4. Escopo

### In Scope (O Que Será Feito)

✅ **Funcionalidades Core**
- [x] Descoberta dinâmica de análises via MCP (agnóstico de cliente)
- [x] Execução de análises contra PostgreSQL
- [x] Execução de análises contra MySQL (adapter)
- [x] Execução de análises contra SQL Server (adapter)
- [x] Execução de análises contra MongoDB (adapter)
- [x] Transformações Python customizadas (handlers)
- [x] Versionamento de análises com histórico
- [x] Cache de resultados (memória local, Redis remoto)
- [x] Servidor MCP via **Streamable HTTP**, acessível por múltiplos clientes simultaneamente na rede local
- [x] Protocolo MCP padrão (sem customizações proprietárias)

✅ **Não-Funcionais**
- [x] Rodar localmente em rede interna (sem exposição pública)
- [x] Portável para remoto (Docker + config parametrizada)
- [x] Zero code changes para novas análises
- [x] Suportar handlers pesados (Celery em ambiente remoto)
- [x] Suportar múltiplos clientes MCP diferentes conectados simultaneamente

### Out of Scope (O Que NÃO Será Feito em V1.0)

❌ **Fora do Escopo V1.0**
- [ ] Interface Web/Dashboard (usar cliente MCP como interface)
- [ ] **Autenticação ou identificação de usuário/cliente MCP** — rede interna é assumida confiável; qualquer pessoa com acesso à rede pode executar análises
- [ ] Rate limiting / quotas por usuário (depende de identificação, fora de escopo)
- [ ] RBAC (controle de acesso por papel)
- [ ] Machine Learning real-time (forecasting é handler, não core)
- [ ] Integração com Salesforce/SAP (extensível via adapters later)
- [ ] Notificações automáticas (manual via cliente MCP pedindo)

---

## 5. Stakeholders e Personas

### Persona Primária: Jose (Developer + Owner)

```
├─ Perfil
│  ├─ iOS, .NET, Python developer
│  ├─ Experiência com FastAPI, MCP
│  ├─ Baseado em rede interna (Brasil)
│  └─ Mantém e configura a plataforma
│
├─ Necessidades
│  ├─ Analisar dados sem escrever SQL/Python novo
│  ├─ Reutilizar análises infinitamente
│  ├─ Versionar mudanças nas análises
│  ├─ Executar localmente na rede interna
│  └─ Funcionar com o cliente MCP de sua preferência
│
├─ Frustrations
│  ├─ Manual SQL repetitivo
│  ├─ Código novo cada mês
│  ├─ Sem histórico de execuções
│  └─ Estar preso a um único cliente MCP
│
└─ Outcomes Desejados
   ├─ "Análise em < 30s com qualquer cliente MCP"
   ├─ "Trocar de cliente sem reconfigurar análises"
   └─ "Histórico completo de análises"
```

### Persona Secundária: Usuário da Rede Interna (End User)

```
├─ Perfil
│  ├─ Não é developer
│  ├─ Usa um cliente MCP de sua preferência (Claude, Gemini, OpenAI, etc.)
│  ├─ Prefere interface conversacional (language-first)
│  └─ Está na mesma rede interna que o servidor
│
├─ Necessidades
│  ├─ Pedir análises em linguagem natural
│  ├─ Não entender SQL ou Python
│  ├─ Resultados confiáveis
│  └─ Usar o cliente MCP que já tem instalado
│
├─ Frustrations
│  ├─ Depender de developers para análises
│  ├─ Respostas lentas
│  └─ Ter que usar um cliente específico se análises só funcionam lá
│
└─ Outcomes Desejados
   ├─ "Análise sob demanda em minutos"
   └─ "Usar meu cliente MCP preferido"
```

### Persona Terciária: Data Engineer (Configurador)

```
├─ Perfil
│  ├─ SQL expert
│  ├─ Entende múltiplos BDs
│  ├─ Responsável por dados e qualidade
│  └─ Sem necessidade de Python avançado
│
├─ Necessidades
│  ├─ Definir análises via SQL puro
│  ├─ Reutilizar handlers customizados (python)
│  ├─ Garantir qualidade e acurácia
│  └─ Suportar múltiplos BDs
│
├─ Frustrations
│  ├─ Repetir mesmas queries todo mês
│  ├─ Sem versionamento de queries
│  └─ Precisa de Python skills para handlers
│
└─ Outcomes Desejados
   ├─ "Config uma vez, usa infinitamente"
   ├─ "SQL puro para configurar"
   └─ "Handlers reutilizáveis"
```

---

## 6. Casos de Uso Principais

### UC1: Cadastrar Nova Análise (Admin)

```gherkin
Feature: Adicionar análise ao sistema

Scenario: Jose quer análise de "Vendas por Região"
  Given José tem acesso ao BD de configuração
  When José insere registro em "analyses" table
  And José insere regras em "analysis_steps" table
  Then MCP descobre análise automaticamente
  And Qualquer cliente MCP conectado lista como opção
  And Análise fica ativa imediatamente
```

**Esforço:** ~5 minutos (tudo SQL)

---

### UC2: Executar Análise (Múltiplos Clientes MCP Simultâneos)

```gherkin
Feature: Pedir análise a qualquer cliente MCP, sem identificação

Scenario: Usuario A quer vendas de setembro (com Claude Desktop)
  Given Usuario A está em Claude Desktop, conectado ao servidor via Streamable HTTP
  When Usuario A pede: "Mostre vendas de setembro por região"
  Then Claude Desktop via MCP chama análise "vendas_por_regiao"
  And Sistema conecta ao BD configurado
  And Executa query + transformações
  And Retorna resultado em < 30s
  And Resultado é cacheado por 1 dia
  And Sistema registra a execução (análise, parâmetros, status, tempo) sem identificar quem pediu

Scenario: Usuario B quer a mesma análise (com Gemini Desktop), ao mesmo tempo
  Given Usuario B está em Gemini Desktop, conectado ao MESMO servidor
  When Usuario B pede a mesma análise
  Then Gemini Desktop via MCP chama a MESMA análise "vendas_por_regiao"
  And Sistema atende a requisição de B independentemente da requisição de A
  And Ambas as execuções ficam registradas no histórico (sem identificar A ou B)
```

**Benefício:** Mesma análise funciona com qualquer cliente MCP, múltiplos usuários ao mesmo tempo, sem necessidade de configurar autenticação.
**Esforço:** ~0 minutos (conversacional, independente do cliente)

---

### UC3: Versionar e Rollback

```gherkin
Feature: Manter histórico de análises

Scenario: Jose quer voltar para versão anterior
  Given Análise "vendas_por_regiao" está na v2
  When Jose descobre que v2 tem erro nos filtros
  And Jose acessa histórico de versões
  Then Sistema mostra v1, v2, v3, etc
  And Jose clica em "Rollback para v1"
  Then Análise volta ao estado anterior
  And Histórico registra a mudança
```

**Esforço:** ~30 segundos

---

### UC4: Adicionar Handler Customizado

```gherkin
Feature: Reutilizar transformações Python

Scenario: Jose quer detectar anomalias
  Given Existe handler "anomaly_detection" em Python
  When Jose insere step na análise com handler="anomaly_detection"
  And Jose configura params (threshold=2.5)
  Then Sistema carrega handler automaticamente
  And Executa transformação nos dados
  And Retorna resultado com anomalias marcadas
  And Nenhum código novo foi escrito
```

**Esforço:** ~2 minutos (SQL + config)

---

## 7. Requisitos Funcionais

### RF1: Descoberta Dinâmica de Análises

```
Dado: Análise configurada no BD
Quando: Um cliente MCP conecta ao servidor via Streamable HTTP
Então:
├─ MCP retorna lista de análises
├─ Cada análise mostra: nome, descrição, parâmetros
├─ Cliente MCP oferece como ferramentas
└─ Análises são sempre up-to-date (sem restart)
```

**Critério de Aceitação:**
- ✅ Leitura do BD sem cache (sempre fresh)
- ✅ Suporta 100+ análises listadas
- ✅ Metadados incluem tipo de parâmetro (string, int, date)
- ✅ Timeout máximo 2s para listar

---

### RF2: Execução de Análises (Multi-Cliente, Sem Autenticação)

```
Dado: Análise "vendas_por_regiao" com steps
Quando: Qualquer cliente MCP conectado ao servidor via Streamable HTTP chama
        execute_analysis(id, params) via MCP
Então:
├─ Sistema conecta ao data_source correto
├─ Executa query SQL parametrizado
├─ Aplica transformações (handlers Python)
├─ Retorna resultado estruturado JSON
└─ Registra execução em log de auditoria (sem identificar cliente/usuário)
```

**Critério de Aceitação:**
- ✅ Suporta PostgreSQL, MongoDB, API
- ✅ Timeout máximo 60s (remoto) / 30s (local)
- ✅ Parâmetros são validados antes de executar
- ✅ Erro contém mensagem clara (não stack trace)
- ✅ Protocolo MCP segue especificação padrão (não proprietário)
- ✅ Suporta múltiplas conexões/clientes simultâneos sem autenticação em V1.0

---

### RF3: Versionamento de Análises

```
Dado: Análise "vendas_por_regiao" v1 está em uso
Quando: Jose modifica a análise
Então:
├─ Sistema cria v2 automaticamente
├─ v1 continua disponível
├─ Histórico mostra: quem mudou, o quê, quando
├─ Possível rollback para v1 em 1 clique
└─ Execuções listam qual versão foi usada
```

**Critério de Aceitação:**
- ✅ Cada mudança cria versão nova
- ✅ Diff entre versões é legível
- ✅ Rollback não deleta histórico
- ✅ Suporta comentários ("por que mudou")

---

### RF4: Handlers Customizados

```
Dado: Handler Python "anomaly_detection" existe
Quando: Análise inclui step com esse handler
Então:
├─ Handler é carregado automaticamente
├─ Recebe dados da query anterior
├─ Retorna dados transformados
├─ Não requer restart da aplicação
└─ Erros no handler são capturados
```

**Critério de Aceitação:**
- ✅ Discovery automático de handlers (built-in + custom)
- ✅ Handlers são Python classes herdando DataHandler
- ✅ Metadata de handler inclui params schema
- ✅ Timeout por handler configurável
- ✅ Falha num handler não quebra pipeline

---

### RF5: Suporte a Múltiplos Bancos de Dados

```
Dado: 4 data sources (PostgreSQL + MySQL + SQL Server + MongoDB)
Quando: Análises usam sources diferentes
Então:
├─ Sistema seleciona adapter correto
├─ Query é executada na "língua" do BD
├─ Resultado é normalizado (JSON comum)
├─ Transformações Python funcionam igual
└─ Sem mudança de código para novo BD
```

**Critério de Aceitação:**
- ✅ Suporta mínimo: PostgreSQL, MySQL, SQL Server, MongoDB
- ✅ Adaptador para API REST (opcional)
- ✅ Novo adapter = 1 classe Python
- ✅ Query validation por tipo de BD

---

## 8. Requisitos Não-Funcionais

### RNF1: Performance

```
├─ Análises leves (< 1s de query): resposta em < 5s
├─ Análises médias (1-5s): resposta em < 15s
├─ Análises pesadas (> 5s): async com status check
├─ Discovery de análises: < 2s
└─ Cache hit: < 100ms
```

### RNF2: Portabilidade

```
├─ Local: docker-compose.local.yml → 1 comando
├─ Remoto: docker-compose.remote.yml → mesmo código
├─ Config por environment (.env file)
├─ Zero mudanças de código local → remoto
└─ Suportar Linux, macOS, Windows (via Docker)
```

### RNF3: Escalabilidade

```
├─ Suportar 100+ análises definidas
├─ Suportar 1000+ execuções/dia
├─ Celery workers escalam horizontalmente (remoto)
├─ Cache garante < 1% queries ao BD
└─ Memory footprint < 500MB (local)
```

### RNF4: Confiabilidade

```
├─ Uptime: > 99% (não crítica, dados não mudam)
├─ Log de execução: 100% das execuções registradas
├─ Concorrência: suportar 10+ conexões/clientes MCP simultâneos
├─ Isolation: erro de 1 execução não afeta outras
├─ Rollback: voltar versão anterior em < 10s
└─ Retry automático: 3x com backoff exponencial
```

### RNF5: Segurança

```
├─ Rede interna: assumir confiável (sem autenticação em V1.0)
├─ Transporte: TLS (HTTPS) obrigatório mesmo em rede interna — requisito de
│  compatibilidade de cliente MCP (confirmado: Claude Desktop recusa conector
│  remoto via http:// simples), não uma política de segurança em profundidade
├─ Credenciais BD: criptografadas em repouso
├─ SQL injection: parametrized queries obrigatório
├─ Validação: todos inputs validados antes execução
└─ Log de execução: qual análise foi executada, quando e com qual resultado
   (sem identificação de usuário/cliente — ver Restrição T5)
```

---

## 9. Restrições

### Restrição T1: Rede Interna Apenas
- ❌ Não expor aplicação na internet
- ✅ Rodar em IP privado (192.168.x.x, 10.x.x.x)
- ✅ Acessível via Streamable HTTP **com TLS (HTTPS)** por qualquer cliente MCP na rede

### Restrição T2: Python 3.11+
- ✅ FastAPI necessita 3.9+
- ✅ Pydantic v2 necessita 3.8+
- ✅ Recomendado 3.11 para performance

### Restrição T3: Banco de Dados Central
- ✅ Config armazenada em BD dedicado (PostgreSQL)
- ✅ Separado do BD de negócio (data sources)
- ✅ Backup obrigatório

### Restrição T4: Transporte MCP via Streamable HTTP (com TLS)
- ✅ Servidor roda como serviço HTTP persistente (uvicorn), não como subprocesso stdio por usuário
- ✅ Cada cliente MCP (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.) se conecta como **conector remoto** (URL), não via `command`/`args` local
- ✅ Múltiplos clientes conectam à mesma instância/porta simultaneamente
- ✅ Endpoint único em `https://<ip>:3000/mcp` (porta 3000, path `/mcp` — convenção padrão do transporte Streamable HTTP do SDK MCP)
- ✅ Substitui o transporte HTTP+SSE (path `/sse`) usado nas versões 1.0-1.3 deste documento
- ✅ **TLS obrigatório** mesmo em rede interna: certificado self-signed local via mkcert para desenvolvimento/máquina única, ou CA interna confiável instalada em cada máquina cliente quando o servidor for acessado por mais de uma máquina na rede (ver ARQUITETURA.md §7 ADR-006 e §9)

### Restrição T5: Sem Autenticação em V1.0
- ✅ Rede interna é assumida confiável — qualquer pessoa/cliente na rede pode executar análises
- ❌ Não requer API Key, OAuth/SSO ou qualquer identificação de usuário em V1.0
- ❌ Não requer identificação de qual cliente MCP está chamando em V1.0
- ⚠️ Antes de expor a aplicação além dessa rede confiável (remoto, internet), autenticação e identificação **devem** ser reintroduzidas (ver seção 12)

---

## 10. Dependências Externas

```
├─ PostgreSQL 13+ (BD de config + data source)
├─ MySQL 8+ (data source opcional)
├─ SQL Server 2019+ (data source opcional, via ODBC)
├─ MongoDB 5+ (data source opcional)
├─ Python 3.11+ (FastAPI runtime)
├─ Cliente(s) MCP compatíveis com Streamable HTTP (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.)
├─ Certificado TLS (mkcert para desenvolvimento/máquina única; CA interna para múltiplas máquinas na rede)
├─ Redis 6+ (cache - remoto apenas)
└─ Docker (para portabilidade)
```

---

## 11. Critérios de Sucesso

### Sprint 1 (MVP Local)
- ✅ FastAPI + servidor MCP via Streamable HTTP rodando localmente
- ✅ 1 análise configurada e funcionando
- ✅ Pelo menos 2 clientes MCP diferentes (ex.: Claude Desktop + Gemini Desktop) conectando **simultaneamente** e listando a análise
- ✅ Execução retornando dados corretos para ambos os clientes

### Sprint 2 (Multi-DB + Versioning)
- ✅ PostgreSQL + MySQL + SQL Server + MongoDB adapters
- ✅ Versionamento funcional
- ✅ 5+ análises diferentes funcionando
- ✅ Rollback testado

### Sprint 3 (Production-Ready)
- ✅ Handler registry funcionando
- ✅ 3 handlers customizados (aggregation, filter, anomaly)
- ✅ Cache local funcional
- ✅ Docker compose (local + remoto)
- ✅ Testes automatizados (80%+ coverage)

### Sprint 4 (Deploy)
- ✅ Documentação completa
- ✅ Logs de execução implementados
- ✅ Teste de carga 100+ análises

---

## 12. Roadmap Futuro (Post V1.0)

```
V1.1: Reintrodução de Identificação (quando necessário)
├─ ClientIdentificationService: qual cliente MCP executou (Claude, Gemini, OpenAI, etc.)
├─ UserIdentificationService: qual pessoa executou, com API Key e quota
├─ Necessário antes de expor a aplicação além da rede interna confiável
└─ Especificação técnica detalhada já existe e pode ser retomada quando este
   requisito voltar ao escopo (repositório de decisões do projeto)

V1.2: Remoto + Escalabilidade
├─ Celery + Redis para production
├─ Kubernetes deployment
├─ Distribuição de cargas
└─ Load balancing entre múltiplos clientes

V1.3: Análises Avançadas
├─ Machine Learning handlers (forecasting, clustering)
├─ Real-time streaming
└─ Alertas automáticos

V1.4: Integrações
├─ Salesforce adapter
├─ SAP adapter
└─ GraphQL gateway
```

### Visão de Longo Prazo (V2.0+)

```
├─ Marketplace de Análises (compartilhar entre organizações)
├─ Suportar qualquer cliente MCP (aberto para novos)
├─ Multi-tenant (múltiplas organizações em 1 plataforma)
└─ MCP como padrão de facto para análises de negócio
```

---

## 13. Posicionamento de Mercado (Diferencial Competitivo)

### Por Que Agnóstico de Cliente MCP É Importante?

**Problema no Mercado Hoje:**
```
Plataforma A: Funciona com um cliente only
├─ Usuario preso a um único cliente
├─ Se o cliente cair, análises não funcionam
└─ Difícil migrar para outro cliente
```

**Nossa Solução:**
```
Nossa Plataforma: Funciona com QUALQUER cliente MCP (protocolo padrão, via Streamable HTTP)
├─ Usuario escolhe o cliente (Claude, Gemini, OpenAI, etc.)
├─ Trocar de cliente = ZERO reconfiguração
├─ Análises funcionam igual em qualquer cliente
├─ Múltiplos usuários com clientes diferentes, ao mesmo tempo, no mesmo servidor
└─ Future-proof: novo cliente MCP aparece? Funciona sem mudança de código
```

### Vantagens Competitivas

| Aspecto | Plataformas Tradicionais | Nossa Solução |
|--------|---------------------------|--------------|
| **Lock-in de cliente** | Alto (preso a 1 cliente) | Zero (funciona com qualquer um) |
| **Flexibilidade** | Baixa | Alta |
| **Custo de Mudança** | Alto | Zero |
| **Multi-cliente simultâneo** | Não | Sim |
| **Portabilidade** | Baixa | Alta |

---

## 14. Glossário

| Termo | Definição |
|-------|-----------|
| **Análise** | Especificação de como extrair, transformar e retornar dados |
| **Data Source** | Conexão a um BD externo (PostgreSQL, MongoDB, etc.) |
| **Handler** | Transformação Python customizável aplicada a dados |
| **Step** | Uma etapa da análise (query, transform, aggregate) |
| **MCP** | Model Context Protocol — protocolo padrão de comunicação com LLMs |
| **Cliente MCP** | Aplicativo que fala MCP com o servidor (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.) |
| **Streamable HTTP** | Transporte MCP via HTTP com endpoint único (`/mcp`), sucessor do antigo transporte HTTP+SSE, permitindo múltiplos clientes remotos/na rede conectados ao mesmo servidor |
| **Versioning** | Histórico de mudanças em análises |
| **Rollback** | Voltar análise para versão anterior |
| **Log de Execução** | Registro de cada execução (análise, parâmetros, status, tempo) |

---

## 15. Aprovações

| Papel | Nome | Data | Assinatura |
|-------|------|------|-----------|
| Product Owner | Jose | 2026-09-22 | ✓ |
| Tech Lead | Claude | 2026-09-22 | ✓ |

---

**Documento finalizado e pronto para arquitetura.**
