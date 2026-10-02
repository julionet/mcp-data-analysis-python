# 🏗️ Documento de Arquitetura

## Plataforma de Análise de Dados Genérica com MCP

**Versão:** 1.23 (Aprovado — Streamable HTTP **stateless, com TLS obrigatório** Multi-Cliente, **com autenticação por token opaco + perfis (F12)**, com PostgreSQL + MySQL + SQL Server + Oracle, **sem Handlers — servidor entrega dataset bruto**, sem Versionamento de Análises)
**Data:** 2026-10-01
**Stack:** FastAPI + Python + PostgreSQL + MCP
**Status:** ✅ Aprovado

> **Nota de revisão (v1.22 → v1.23):** F9 (Oracle Adapter) **implementada** (2026-10-01), sem mudança de decisão arquitetural. `OracleAdapter` (`adapters/oracle.py`) registrado no `AdapterFactory` (§4.2); `oracledb>=2.0.0` em `requirements.txt` (§5.1, modo thin, sem dependência de SO). Tradução `:x` → `:pN` por índice de `param_names` (mesmo contrato do PostgreSQL: `params` chega na ordem de `param_names`); chaves de coluna em minúsculas; `connect()` valida uma conexão (o pool async do driver é preguiçoso). Alias do wrapper `COUNT(*)` do Volume Guard: `AS sub` → `sub` em `analysis_service._run_query()` (aceito pelos 4 bancos). Sem validação manual (sem instância Oracle). Spec e histórico: `features/F9_ORACLE_ADAPTER.md` §11.
>
> **Nota de revisão (v1.21 → v1.22):** F12 **implementada** (2026-09-30): `POST /auth/token` e `POST /auth/revoke` (`routes/auth.py`), `AuthMiddleware` ASGI + `contextvar` no `/mcp` (transporte stateless), `AuthService`, repositórios `UserRepository`/`ProfileRepository`/`AccessTokenRepository`, `list_tools()` filtrado por perfil e `call_tool()` com revalidação de permissão, `execution_history.user_id`. Testes: 295 ✅ (189 anteriores ajustados + 106 novos). Migration: `analysis_app/database/migrations/f12_autenticacao.sql`; seed de exemplo: `analysis_app/database/seed_usuario_admin_f12.sql`. Validado com cliente MCP real via `mcp-remote --header`. Spec e notas de implementação: `features/F12_AUTENTICACAO_PERFIS.md` §11. Decisões de implementação que refinam §3.5/ADR-007 (sem mudar o desenho): (1) o `AuthMiddleware` envolve diretamente os dois endpoints do `/mcp` (rota exata e mount), sem filtro de path — fail-closed; (2) o SDK `mcp` chama `list_tools()` em todo `tools/call` para validar o input, o que adiciona uma query de permissão por chamada; (3) `_validate_credentials()` sempre executa um bcrypt (hash fictício quando o e-mail não existe) para tempo de resposta constante; (4) os handlers MCP são fail-closed: sem usuário no `contextvar` nada é listado nem executado.
>
> **Nota de revisão (v1.20 → v1.21):** correção do **racional** do transporte stateless (sem mudança de decisão — `stateless=True` continua). A nota v1.19 dizia que, com sessão, um usuário bloqueado "continuaria usando uma sessão já aberta"; isso só vale se o token fosse validado apenas no `initialize` — o middleware do F12 valida toda requisição, então o bloqueio imediato funcionaria também em stateful. O motivo real, comprovado em teste no SDK `mcp` 1.x: em stateful o `StreamableHTTPSessionManager` cria a task do servidor uma única vez, no `initialize`, e ela reaproveita o contexto daquela requisição — o `contextvar` do `AuthenticatedUser` fica congelado no usuário que abriu a sessão, e requisições seguintes com outro token executariam com as permissões dele (confusão de identidade). Em stateless a task nasce dentro de cada requisição e herda o `contextvar` correto. Atualizados: nota técnica de §3.5, consequência v1.19 do ADR-006 (§7) e nova lição técnica §14.1 item 8. `expose_headers` do CORS passa a `["WWW-Authenticate"]` (F12) — `Mcp-Session-Id` nunca é enviado em stateless.
>
> **Nota de revisão (v1.19 → v1.20):** F12 passa a emitir token por **e-mail e senha**, pelo próprio usuário (revisão de ADR-007; sem mudança no formato do token nem na autorização por perfis). (1) Novos endpoints `POST /auth/token` (e-mail, senha, `label` e `expire_days` opcionais; `expire_days` limitado por `ACCESS_TOKEN_MAX_EXPIRATION_DAYS`) e `POST /auth/revoke` (e-mail, senha e token; credenciais validadas antes do token; 404 para token inexistente ou de outro usuário), em `routes/auth.py`, registrados em `main.py`, fora do middleware do `/mcp` — §3.5. (2) `users` ganha `password_hash` (bcrypt); `external_id` vira o e-mail de login (minúsculas, normalizado pela aplicação) — §2.2. (3) `scripts/generate_access_token.py` removido — §5.2, §8, §9. (4) Nova dependência `bcrypt` — §5.1; novas variáveis `ACCESS_TOKEN_MAX_EXPIRATION_DAYS` — §8.2. (5) ADR-007 revisado: emissão self-service em vez de administrativa; consequência registrada — os endpoints ampliam a superfície de ataque e V1.0 não tem proteção contra tentativas de senha (só log). (6) Falhas de login e revogação com log próprio (sem senha e sem e-mail) — F12 §4.5. (7) Revisão final do F12: datas de `access_tokens` em `TIMESTAMPTZ` (asyncpg devolve `TIMESTAMP` sem fuso e a comparação com `datetime.now(timezone.utc)` falharia); `users.is_blocked` e `profiles.is_active` `NOT NULL DEFAULT`; árvore de pastas §5.2 corrigida (sem `models.py`/Alembic — o schema é `database/schema.sql` + `database/migrations/f12_autenticacao.sql`).
>
> **Nota de revisão (v1.18 → v1.19):** transporte MCP passa a **stateless** (`StreamableHTTPSessionManager(app=mcp_server, stateless=True)`, `mcp_transport/__init__.py`) — pré-requisito do F12, já aplicado no código e validado (F6 com 2+ clientes reais + `TestStatelessTransport` em `tests/test_server_setup.py`, 189/189 testes ✅). Racional: com sessão (`stateless=False`, padrão do SDK) o servidor mantém `Mcp-Session-Id` entre requisições, e um usuário bloqueado ou token revogado continuaria usando uma sessão já aberta — contradiz o requisito de bloqueio imediato do F12. Em stateless cada requisição HTTP é independente e é autenticada por conta própria. Registrado em ADR-006 (nova consequência) e na nota técnica de §3.5 (threading do `AuthenticatedUser` decidido: middleware ASGI + `contextvar`). Nenhuma outra decisão arquitetural mudou.

> **Nota de revisão (v1.17 → v1.18):** F11 (SQL Server Adapter) implementado (2026-09-29), sem mudança de decisão arquitetural — `SQLServerAdapter` (`adapters/sqlserver.py`) registrado no `AdapterFactory` (§4.2). Detalhes de implementação: `translate_params()` gera `@nome` e `execute_query()` converte para `?` na ordem de ocorrência (o pyodbc só aceita parâmetros posicionais; o contrato do `DatabaseAdapter` não mudou); pool `aioodbc` com `minsize=1`/`maxsize=10` (o default 10/10 abriria 10 conexões no primeiro uso); autocommit; timeout de query via `settings.query_timeout_seconds`; `sslmode` mapeado para `Encrypt`/`TrustServerCertificate`; senha escapada em `PWD={...}`; autenticação somente usuário/senha SQL (sem Integrated Auth); driver ODBC configurável em `connection_config.driver` (padrão `ODBC Driver 18 for SQL Server`). Os erros nativos 1033/8155/8156 do wrapper `SELECT COUNT(*) FROM (<sql>) AS sub` são relançados com mensagem explicando a restrição de SQL; a mensagem fica no log do servidor, pois o `AnalysisService` continua devolvendo mensagem genérica ao cliente MCP. **Subconjunto comum de SQL** (sem `ORDER BY`/CTE/`;` no topo, colunas com nome único e explícito, todo parâmetro declarado presente no SQL) documentado em `features/F11_SQLSERVER_ADAPTER.md` §8.4. Novo `tests/test_adapter_contract.py`: contrato de parâmetros agnóstico entre PostgreSQL, MySQL e SQL Server. Pendências registradas em F11 §10 (`sslmode` ignorado por PostgreSQL/MySQL; PostgreSQL depende de `params` na ordem de `param_names`).
>
> **Nota de revisão (v1.16 → v1.17):** limpeza pós-Sprint 1/2 (sem mudança de decisão arquitetural). (1) `analysis_version_id` removida de `execution_history` (§2.2) — a coluna era mantida "para compatibilidade futura" com FB6/FB7, mas a tabela `analysis_versions` já tinha saído do schema; se o versionamento voltar, a coluna volta junto com a tabela, via migration. `ExecutionRepository.create()` e `AuditService.log_execution()` deixam de passar esse parâmetro. (2) `docker-compose.local.yml` e `docker-compose.remote.yml` (arquivos vazios) removidos do repositório e de §5.2/§9.1 — voltam com a **F13 (Docker Setup)**. (3) Lições técnicas do protótipo F0 consolidadas na nova §14.1, para que `mcp_prototype/README.md` deixe de ser a única fonte. (4) **O engine só executa `SELECT`**: `AnalysisService` valida o SQL do step (`schemas/sql_validation.py`) antes de tocar o data source — recusa INSERT/UPDATE/DELETE/DDL, `SELECT ... INTO`, `;` e CTE (`WITH`, já fora do subconjunto comum de SQL); é rede de segurança contra erro de cadastro, não fronteira de segurança — o usuário do data source deve ter permissão somente de leitura (§8.2). Análise sem step também passa a devolver erro claro. (5) MySQL passa a ter timeout de query via `SET SESSION max_execution_time` (`init_command` do pool; exige MySQL ≥ 5.7.8, MariaDB usa `max_statement_time`). (6) `CacheService` libera o lock de cada chave ao final (antes o dict `_locks` crescia sem limite) e `ExecutionRepository.get_all()` deixa de chamar um `fetch()` inexistente no adapter.

> **Nota de revisão (v1.15 → v1.16):** documento aprovado. Adicionada autenticação (**F12** — ver FEATURES_ROADMAP.md v1.12 e NEGOCIO.md v1.9 RF5): novo **ADR-007** (reintroduzido com um desenho diferente do ADR-007 original removido na v1.2 — token opaco em vez de API Key simples, com perfis N:N) decide token opaco (hash SHA-256) em vez de JWT ou OAuth2, com o racional completo das 3 alternativas comparadas. Novas tabelas no schema (§2.2): `users`, `profiles`, `user_profiles`, `profile_analyses`, `access_tokens`; `execution_history` ganha `user_id` (nullable). Novos componentes (§2.1): `AuthService` na camada de Services, `UserRepository`/`ProfileRepository`/`AccessTokenRepository` na camada de Data Access. Nova seção **§3.5** (Fluxo de Autenticação e Autorização). `mcp_transport/tools.py` (`list_tools`/`call_tool`) passa a exigir um `AuthenticatedUser` resolvido a partir do header `Authorization: Bearer <token>`. Atualizados: §1.2 (topologia — exemplo de config de cliente com header), §2.1, §2.2, nova §3.5, §5.2 (estrutura de pastas — `security/token_auth.py`, novos repos, `scripts/generate_access_token.py`), §8.1 (autenticação sai de "❌ Não implementar" para "✅ Implementar"), §9.1 (exemplo de config de cliente), §12 (Roadmap Arquitetural), §13 (tabela de tecnologias). Nenhuma dependência nova em `requirements.txt` — o mecanismo usa só `secrets`/`hashlib` da stdlib. Spec completa: `features/F12_AUTENTICACAO_PERFIS.md`.

> **Nota de revisão (v1.14 → v1.15):** MongoDB removido de V1.0 e substituído por **Oracle** (F9 — ver `features/F9_ORACLE_ADAPTER.md`). Atualizados: diagrama de contexto (§1.1), componentes (§2.1), comentário do schema (§2.2), Factory (§4.2), dependências (§5.1: `motor` → `oracledb>=2.0.0`; `aioodbc`/`pyodbc` sem pin exato — `pyodbc==5.0.1` não tem wheel para Python 3.13; validado com `aioodbc 0.5.0`/`pyodbc 5.3.0`), estrutura de pastas (§5.2), startup (§6.1), exemplo de `.env` (§8.2, sem `MONGODB_CONNECTION_STRING` — credenciais de data source vêm de `connection_config`) e tabela de tecnologias (§13). Com o MongoDB fora, todos os adapters são SQL e o wrapper de `COUNT(*)` do Volume Guard vale para todos. Regras do subconjunto comum de SQL (sem `ORDER BY`/CTE/`;` no topo, colunas com nome único, todo parâmetro declarado presente no SQL) registradas em F11 §8.4 e F9 §8.4. Oracle usa `oracledb` em thin mode (sem dependência de SO — só o SQL Server exige driver ODBC no `Dockerfile` do F12). O alias do wrapper passa de `AS sub` para `sub` (Oracle rejeita `AS` em alias de tabela; PostgreSQL, MySQL e SQL Server aceitam) — F9 §4.1. Ordem de implementação da Sprint 2: F10 ✅ → F11 → F9.

> **Nota de revisão (v1.13 → v1.14):** Removidas `VersionService` e `VersionRepository` inteiramente (F9 e F10 foram removidos da Sprint 2 — ver FEATURES_ROADMAP.md v1.9). Justificativa: como a plataforma não implementa Handlers (apenas dataset bruto via servidor), a "análise" é apenas uma query SQL parametrizada configurada 1 vez no BD, sem necessidade de versionar. Mudanças em SQL são alterações diretas na tabela `analyses`, rastreadas via schema versionamento (git + migration histórico). Tabela `analysis_versions` e índice `idx_versions_analysis` removidas do schema (§2.2). Coluna `analysis_version_id` mantida em `execution_history` como NULL por agora — se FB6/FB7 forem reintroduzidos futuro, a coluna FK já existe. Referências removidas de §2.1, §2.2, §3.3, §5.2. Nenhuma outra alteração arquitetural.

> **Nota de revisão (v1.12 → v1.13):** F8 (Log de Execução) foi implementado. Componentes novos: `AuditService` (services/) persiste em `execution_history` via `ExecutionRepository` (repositories/). Método abstrato `execute()` adicionado a `DatabaseAdapter` para operações DML; implementado em `PostgreSQLAdapter`. Fluxo: `AnalysisService._execute()` chama `AuditService.log_execution()` após resolução de `analysis_id`, registrando success/volume_exceeded/error com execution_time_ms, rows_affected, result_size_bytes, cached flag. AnalysisNotFoundError não é logado (evita violar FK). Nenhuma alteração nas decisões arquiteturais do documento — apenas adição de um novo serviço/repositório confirmado e de um novo método base abstrato para DML.

> **Nota de revisão (v1.11 → v1.12):** revisão de documentação/implementação (sem mudança de decisão arquitetural). Duas correções: (1) §2.1, §5.2 e §6.1 corrigidos para não listar `list_resources()`/`read_resource()` como entregues — F5_MCP_TOOLS_INTEGRATION.md §3 já documentava a decisão de não implementá-los em V1.0 (sem requisito de negócio), mas o diagrama de componentes, a estrutura de pastas e o fluxo de startup aqui ainda os listavam como se existissem; `mcp_transport/resources.py` nunca foi criado. (2) Removida a pasta `handlers/` (stubs vazios `handlers/`, `handlers/built_in/`, `handlers/custom/`) que sobrevivera no código após a remoção formal da camada de Handlers no ADR-005 (v1.9) — código morto, sem referência em nenhum documento aprovado. Ver também F4_EXECUTION_ENGINE.md, nota de ajuste retroativo de 2026-09-26 (pool de conexão por data_source e timeout de query), que não altera nada neste documento além do já previsto em §8.1.
>
> **Nota de revisão (v1.10 → v1.11):** documento aprovado. Corrigida contradição em §8.1 ("Rede Interna, Sem Autenticação (V1.0)") com o ADR-006 (§7), com o §9.1 e com o F1 já implementado: TLS (HTTPS) e CORS estavam listados em "❌ Não implementar em V1.0", mas ambos já são obrigatórios/implementados desde o F1 — TLS porque clientes MCP reais recusam conector remoto via `http://` simples mesmo em rede interna confiável, e CORS porque clientes desktop validam o conector via `fetch()` no processo de renderer. As duas entradas foram movidas para "✅ Implementar em V1.0", com o motivo técnico (compatibilidade de cliente MCP, não política de segurança em profundidade) referenciando o ADR-006. Removida do bloco "⚠️ Futuro" a linha "SSL/TLS entre cliente → servidor" (já implementado em V1.0, deixa de ser item futuro); nenhum item novo foi colocado no lugar por não haver, em nenhum documento existente, uma definição do que realmente falta em segurança de transporte para V1.1+ — a decidir numa próxima revisão.
>
> **Nota de revisão (v1.9 → v1.10):** F5 (MCP Tools Integration) implementada — `list_tools()`/`call_tool()` reais em `mcp_transport/tools.py`, consumindo `AnalysisService`/`AnalysisRepository.get_by_name()` (F5_MCP_TOOLS_INTEGRATION.md). Duas correções de nomenclatura/contrato aplicadas retroativamente em toda a documentação (§3.4, F3, F4) para bater com o texto já aprovado da spec F5: (1) o status de recusa por volume passa a se chamar **`volume_exceeded`** (era `refinamento_necessario` desde a v1.9 — mesmo formato de payload, só o nome do status mudou); (2) `AnalysisService.execute()` deixa de propagar exceção — todo caminho de saída é um dict `{"status": "success"|"volume_exceeded"|"error", ...}`, e o parâmetro `confirmar_volume_alto` agora é aceito diretamente por `execute()` (bypass real dos dois checks de volume, com `"aviso"` no payload de sucesso).
>
> **Nota de revisão (v1.8 → v1.9):** documento aprovado. Removida inteiramente a camada de **Handlers Python** do servidor — `HandlerRegistry`, pasta `handlers/`, `HandlerRepository`, ADR-005 e a tabela `custom_handlers` do schema (decisão: remover, não manter tabela sem uso — o projeto ainda não está em produção, então não há risco de `DROP TABLE` destrutivo). O servidor deixa de transformar dados: executa a query parametrizada e devolve o **dataset bruto** ao cliente MCP, que interpreta/agrega os dados do lado do LLM. Em troca, ganha uma nova camada de **Controle de Volume** (`VolumeGuardService`): pré-checagem via `SELECT COUNT(*)`, checagem de tamanho serializado em KB, e recusa estruturada com pedido de refinamento (ou confirmação explícita via parâmetro reservado `confirmar_volume_alto`) — ver nova seção **§3.4**. Limites (`DEFAULT_MAX_RESULT_ROWS`, `DEFAULT_MAX_RESULT_SIZE_KB`) são 100% globais via `.env`, sem override por análise. Atualizados: §1.2, §2.1, §2.2 (schema), nova §2.3 (formato de `analyses.parameters` e conversão para JSON Schema MCP), §3.1, §3.2, nova §3.4, §4.3 (era Registry Pattern, agora Volume Guard), §5.1 (`cryptography`/Fernet), §5.2 (estrutura de pastas), §6.1 (startup), §7 (ADR-005 reescrito), §8.2 (formaliza Fernet para `connection_config.password`), §10.3, §11, §13, §14. Ver `PROPOSTA_REVISAO_HANDLERS_E_VOLUME.md` para o racional completo e NEGOCIO.md v1.6 / FEATURES_ROADMAP.md v1.6 para as mudanças correspondentes nos outros documentos.

> **Nota de revisão (v1.1 → v1.2):** removidos `ClientIdentificationService`, `UserIdentificationService`, as tabelas `mcp_clients`, `users`, `user_api_keys`, e os ADRs de autenticação (eram ADR-007 e ADR-008). O transporte deixou de ser descrito como stdio (subprocesso local por usuário) e passou a ser **HTTP+SSE**, um único serviço na rede interna acessível por múltiplos clientes MCP simultaneamente. Também corrigida a ordem de criação de tabelas no schema (havia uma FK para uma tabela definida mais adiante) e a numeração duplicada de seções (havia duas seções "12" e duas "13").

> **Nota de revisão (v1.2 → v1.3):** documento aprovado. Adicionado **SQLServerAdapter** como adapter de primeira classe em V1.0 (via ODBC/`aioodbc`), ao lado de PostgreSQL, MySQL e MongoDB (ver §2.1, §4.2, §5.1, §13).

> **Nota de revisão (v1.3 → v1.4):** documento aprovado. Trocado o transporte MCP de **HTTP+SSE** (endpoint `/sse`) para **Streamable HTTP** (endpoint único `/mcp`), o transporte mais recente da especificação MCP. Atualizados: ADR-006 (§7), diagrama de contexto (§1.1), topologia local (§1.2), exemplo de configuração de cliente, stack técnico (§5.1 — dependência `mcp` do SDK), estrutura de pastas (§5.2) e fluxo de inicialização (§6.1). Porta permanece 3000; nenhuma outra decisão de arquitetura foi alterada.

> **Nota de revisão (v1.4 → v1.5):** documento aprovado. O protótipo F0 (`F0_PROTOTIPO_MCP_MEMORIA.md`) validou a decisão do ADR-006 na prática e revelou 4 ajustes técnicos necessários para o F1 real: (1) **TLS agora é obrigatório mesmo em rede interna** — clientes MCP reais (confirmado: Claude Desktop) recusam conector remoto via `http://` simples, independente da rede ser confiável; (2) a dependência `mcp` precisa de teto de versão — a v2.0.0 do SDK remove os decorators `list_tools()`/`call_tool()` da classe de baixo nível `Server` usada no ADR-006; (3) o handshake TLS precisa negociar ALPN explicitamente (a CLI padrão do uvicorn não faz isso, exigindo `ssl_context_factory` programático); (4) o endpoint MCP montado via `app.mount()` sob FastAPI precisa de uma rota exata adicional para o path sem barra final, evitando um redirect 307 que alguns clientes não toleram bem. Atualizados: ADR-006 (§7), §5.1 (dependências), §9.1 (plano de implantação local), nova nota em §6.1.

> **Nota de revisão (v1.5 → v1.6):** documento aprovado. Adicionada uma nova seção **§9.2 Produção Interna (nginx + Certbot)** — um servidor de produção dedicado, ainda em rede interna (Restrição T1 continua valendo), usando nginx como reverse proxy para terminação TLS e Certbot para emissão/renovação de certificado. Documentadas as duas estratégias possíveis para o Certbot: desafio DNS-01 contra um domínio público (não exige expor o servidor à internet, só o DNS do domínio) ou uma CA interna própria compatível com ACME (sem depender de domínio público, mas exige instalar essa CA em cada máquina cliente). A antiga §9.2 (Remoto — Futuro, Kubernetes) foi renumerada para §9.3. Nenhuma outra decisão de arquitetura foi alterada — o app continua servindo `/mcp` sem autenticação (ADR-006).

> **Nota de revisão (v1.6 → v1.7):** documento aprovado. Explicitada em §9.2 a diferença de exigência de confiança do cliente entre as duas opções de Certbot: a Opção A (DNS-01/Let's Encrypt) não exige nenhuma configuração nos clientes MCP, porque a CA do Let's Encrypt já vem pré-instalada por padrão em qualquer sistema operacional/runtime — igual a qualquer API pública comum; a Opção B (CA interna) exige instalar/confiar nessa CA em cada máquina cliente, exatamente como o mkcert em §9.1. A distinção não é "nginx+Certbot vs. mkcert", é se a CA emissora já é publicamente confiável de fábrica ou é uma CA privada criada para esse ambiente.

> **Nota de revisão (v1.7 → v1.8):** documento aprovado. Renomeada em §5.2 a pasta `mcp/` para **`mcp_transport/`** — durante a implementação de F1 (`F1_IMPLEMENTACAO.md`), constatou-se que um pacote local chamado `mcp/` colide com o SDK `mcp` que ele mesmo importa (`from mcp.server.lowlevel import Server`): rodando o processo a partir de `analysis_app/` (padrão usado desde o protótipo F0), o Python resolve `import mcp` para o pacote local em vez do SDK instalado, quebrando com `ModuleNotFoundError: No module named 'mcp.server'`. Nenhuma outra decisão de arquitetura foi alterada — apenas o nome da pasta em §5.2.

---

## 1. Visão Arquitetural

### 1.1 Contexto Geral

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Claude Desktop │  │  Gemini Desktop │  │ OpenAI Desktop  │  ... (qualquer cliente MCP)
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                     │
         └────────────────────┼─────────────────────┘
                               │  Streamable HTTP (mesma porta, mesma instância)
                               ▼
┌─────────────────────────────────────────────────────────┐
│           FastAPI MCP Server (Port 3000, Streamable HTTP)       │
│  ├─ Discovery: lista análises dinâmicas                 │
│  ├─ Execution: executa análise selecionada              │
│  └─ Logging: registra execuções (sem identificação)     │
└─────────────────────────────────────────────────────────┘
            ↓              ↓              ↓              ↓
      ┌───────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐
      │PostgreSQL │  │  MySQL   │  │SQL Server │  │   Oracle     │
      │(Config+DB)│  │(Data Src)│  │(Data Src) │  │ (Data Source)│
      └───────────┘  └──────────┘  └───────────┘  └──────────────┘
```

**Ponto-chave:** o servidor é um **processo HTTP persistente** (`uvicorn main:app --host 0.0.0.0 --port 3000`), não um subprocesso disparado por `command`/`args` de um cliente MCP. Cada cliente se conecta como **conector remoto** (URL), e vários clientes — inclusive de fabricantes diferentes — podem estar conectados ao mesmo tempo.

### 1.2 Topologia Local vs Remoto

#### **Local (Rede Interna — Multi-Cliente, Autenticado por Token)**
```
┌────────────────────────────────────────┐
│   Máquina na Rede Interna              │
│  ├─ Processo uvicorn (porta 3000)     │
│  │  ├─ FastAPI Server                 │
│  │  ├─ MCP Interface (Streamable HTTP)       │
│  │  ├─ AuthService (token opaco)      │
│  │  └─ Volume Guard (pré-check)       │
│  ├─ PostgreSQL (config)                │
│  └─ PostgreSQL (data source)           │
└────────────────────────────────────────┘
     ↑                ↑                ↑
Claude Desktop   Gemini Desktop    OpenAI Desktop
(conector remoto)(conector remoto) (conector remoto)
(via Streamable HTTP)   (via Streamable HTTP)    (via Streamable HTTP)
(Bearer token X)        (Bearer token Y)         (Bearer token Z)

Nota: qualquer cliente MCP compatível com Streamable HTTP e capaz de enviar
um header customizado funciona — cada usuário/cliente usa seu próprio token
(ver ADR-007, §3.5).
```

**Exemplo de configuração no cliente (formato varia por app, mas o conceito é o mesmo):**
```json
{
  "mcpServers": {
    "analysis": {
      "url": "https://192.168.1.50:3000/mcp",
      "headers": {
        "Authorization": "Bearer <token obtido em POST /auth/token>"
      }
    }
  }
}
```

> `https://`, não `http://` — TLS é obrigatório mesmo em rede interna (ver ADR-006). Certificado confiável nas máquinas clientes: mkcert (máquina única) ou CA interna instalada em cada cliente (múltiplas máquinas).
Sem `command`, `args` ou `env` — o servidor já está rodando de forma independente na rede; o cliente só aponta para a URL. O campo exato para o header de autenticação varia por cliente MCP (alguns usam `headers`, outros um campo dedicado "API Key"/"Token") — o conceito (`Authorization: Bearer <token>`) é o mesmo em todos.

#### **Remoto (Produção — Futuro)**
```
                    ┌─────────────────────────────────────┐
                    │     Qualquer cliente MCP (via HTTP)  │
                    │ ├─ Claude Desktop / API              │
                    │ ├─ Gemini Desktop / API              │
                    │ ├─ OpenAI Desktop / API               │
                    │ └─ Novos clientes (futuros)          │
                    └────────────┬──────────────────────────┘
                                 ↓
┌──────────────────────────────────────────────────────┐
│         Kubernetes Cluster (HA)                      │
│  ┌────────────────────────────────────────────┐    │
│  │ FastAPI MCP Servers (replicas)             │    │
│  │  ├─ MCP Interface (Streamable HTTP)               │    │
│  │  └─ Volume Guard (pré-check)                │    │
│  ├────────────────────────────────────────────┤    │
│  │ Celery Workers (replicas)                  │    │
│  │  └─ Execução de queries pesadas/demoradas  │    │
│  ├────────────────────────────────────────────┤    │
│  │ Redis Cluster (Cache + Task Queue)         │    │
│  ├────────────────────────────────────────────┤    │
│  │ PostgreSQL (HA) — Config DB                │    │
│  └────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘

⚠️ Ao expor remotamente (fora da rede confiável), autenticação por token
(já implementada em V1.0, ver ADR-007) deixa de ser suficiente sozinha —
identificação de cliente MCP, rate limiting e SSO/OAuth DEVEM ser avaliados
(ver §12).
```

---

## 2. Componentes Principais

### 2.1 Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Application                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │    MCP Server Interface (Streamable HTTP, Multi-Cliente)   │   │
│  │                                                      │   │
│  │  Aceita de QUALQUER cliente MCP compatível          │   │
│  │  com Streamable HTTP, simultaneamente, autenticado  │   │
│  │  por token (Authorization: Bearer <token>, ver §3.5):│   │
│  │  ├─ Claude Desktop                                  │   │
│  │  ├─ Gemini Desktop                                  │   │
│  │  ├─ OpenAI Desktop                                  │   │
│  │  └─ Qualquer futuro cliente com MCP padrão          │   │
│  │                                                      │   │
│  │  Endpoints Padrão MCP (ambos exigem token válido    │   │
│  │  e resolvem AuthenticatedUser antes de prosseguir): │   │
│  │  ├─ list_tools()         → analyses liberadas       │   │
│  │  │                          para o usuário (§3.5)   │   │
│  │  └─ call_tool()          → revalida permissão e     │   │
│  │                             executa análise         │   │
│  │  (list_resources()/read_resource() disponíveis no  │   │
│  │   SDK mas não implementados em V1.0 — decisão do   │   │
│  │   F5, ver F5_MCP_TOOLS_INTEGRATION.md §3: sem      │   │
│  │   requisito de negócio que os justifique)          │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Services (Business Logic)                  │   │
│  │  ├─ AnalysisService                                │   │
│  │  │  ├─ execute(analysis_id, params)                │   │
│  │  │  ├─ get_all_analyses()                          │   │
│  │  │  └─ validate_analysis(schema)                   │   │
│  │  ├─ VolumeGuardService                             │   │
│  │  │  ├─ check_row_count(sql, params)                │   │
│  │  │  ├─ check_serialized_size(result)                │   │
│  │  │  └─ build_refinement_response(estimate, limit)   │   │
│  │  ├─ CacheService (usado dentro de AnalysisService.execute() —│   │
│  │  │  │  F7_CACHE_SERVICE.md §3; CacheBackend abstrai troca    │   │
│  │  │  │  futura por Redis — só InMemoryBackend em V1.0)        │   │
│  │  │  ├─ build_key(analysis_id, updated_at, params) -> str    │   │
│  │  │  ├─ resolve_ttl(cache_frequency) -> int | None           │   │
│  │  │  └─ get_or_execute(key, ttl, confirmar_volume_alto, executor) │   │
│  │  │     (invalidate_by_source fora do F7 — backlog futuro)   │   │
│  │  ├─ AuditService (grava execution_history.user_id, │   │
│  │  │  │  quando disponível — F12)                    │   │
│  │  │  ├─ log_execution(analysis_id, params, result,  │   │
│  │  │  │                 user_id)                     │   │
│  │  │  └─ get_execution_history()                     │   │
│  │  └─ AuthService (F12 — ver §3.5, ADR-007)           │   │
│  │     ├─ authenticate(raw_token) -> AuthenticatedUser │   │
│  │     ├─ issue_token(email, password, label,          │   │
│  │     │               expire_days) -> (token, exp)    │   │
│  │     ├─ revoke_token(email, password, raw_token)     │   │
│  │     └─ get_allowed_analysis_ids(user_id) -> set[UUID]│  │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Adapters (Database Access)                 │   │
│  │  ├─ DatabaseAdapter (Abstract)                     │   │
│  │  ├─ PostgreSQLAdapter                              │   │
│  │  ├─ OracleAdapter                                  │   │
│  │  ├─ MySQLAdapter                                   │   │
│  │  ├─ SQLServerAdapter                               │   │
│  │  └─ APIAdapter                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Data Access (Repository)                   │   │
│  │  ├─ AnalysisRepository                             │   │
│  │  ├─ DataSourceRepository                           │   │
│  │  ├─ ExecutionRepository                            │   │
│  │  ├─ UserRepository (F12)                           │   │
│  │  ├─ ProfileRepository (F12)                        │   │
│  │  └─ AccessTokenRepository (F12)                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Banco de Dados — Schema

> Ordem de criação corrigida: nenhuma tabela referencia outra que ainda não existe.

```sql
-- Banco: analysis_config (PostgreSQL local)

-- Tabela 1: Fontes de Dados
CREATE TABLE data_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    type VARCHAR(50) NOT NULL,  -- postgresql, mysql, sqlserver, oracle, api
    connection_config JSONB NOT NULL,  -- {host, port, database, user, password (Fernet), sslmode} — ver §8.2
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 2: Análises (definições)
CREATE TABLE analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    data_source_id UUID REFERENCES data_sources(id),
    cache_frequency VARCHAR(50) DEFAULT 'daily',
    parameters JSONB,  -- schema dos parâmetros aceitos
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 3: Etapas da Análise
CREATE TABLE analysis_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    step_order INT NOT NULL,
    step_type VARCHAR(50) NOT NULL,  -- query (único tipo em uso em V1.0; coluna mantida
                                      -- para permitir múltiplas queries por análise)
    definition JSONB NOT NULL,  -- {sql, params, ...}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(analysis_id, step_order)
);

-- Tabela 4: Usuários com acesso à plataforma (F12)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    external_id VARCHAR(255) UNIQUE,  -- e-mail de login (F12), cadastrado em minúsculas; a app normaliza o e-mail recebido
    password_hash VARCHAR(255),       -- hash bcrypt da senha (F12); NULL = usuário não consegue emitir token
    is_blocked BOOLEAN NOT NULL DEFAULT false,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 5: Perfis de acesso (F12)
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabela 6: N:N usuário <-> perfil (F12)
CREATE TABLE user_profiles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, profile_id)
);

-- Tabela 7: N:N perfil <-> analyses (F12)
CREATE TABLE profile_analyses (
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    analysis_id UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    PRIMARY KEY (profile_id, analysis_id)
);

-- Tabela 8: Tokens de acesso — opacos, só o hash é persistido (F12)
CREATE TABLE access_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,  -- SHA-256 hex do token bruto
    label VARCHAR(255),                    -- ex.: "Claude Desktop - notebook Julio"
    expires_at TIMESTAMPTZ NOT NULL,       -- TIMESTAMPTZ: asyncpg devolve datetime com fuso (comparação com now(UTC) em Python)
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

-- Tabela 9: Histórico de Execuções (F12 adiciona user_id — quem executou)
CREATE TABLE execution_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id UUID NOT NULL REFERENCES analyses(id),
    user_id UUID REFERENCES users(id),  -- nullable: quem executou (F12); NULL para execuções pré-F12; sem ON DELETE: impede apagar usuário com histórico

    parameters JSONB,
    status VARCHAR(50),  -- success, failed, timeout
    execution_time_ms INT,
    rows_affected INT,
    result_size_bytes INT,
    error_message TEXT,
    result_location VARCHAR(500),  -- path/uri do resultado
    executed_at TIMESTAMP DEFAULT NOW(),
    cached BOOLEAN DEFAULT false
);

-- Índices para performance
CREATE INDEX idx_analyses_active ON analyses(is_active);
CREATE INDEX idx_execution_history_analysis ON execution_history(analysis_id);
CREATE INDEX idx_execution_history_executed_at ON execution_history(executed_at);
CREATE INDEX idx_execution_history_user ON execution_history(user_id);
-- (sem índice em token_hash: o UNIQUE de access_tokens.token_hash já cria um índice)
CREATE INDEX idx_access_tokens_user ON access_tokens(user_id);
```

> As tabelas `mcp_clients` e `user_api_keys` (do desenho original de FB1/FB2, removido em v1.2) seguem fora de V1.0 — `mcp_clients` porque identificação de cliente MCP/software (FB1) continua sem requisito de negócio; `user_api_keys` porque F12 (§2.2 acima) usa um desenho diferente (`access_tokens`, token opaco com hash, sem "API Key" nomeada por serviço externo). As colunas `client_llm_name`, `client_llm_version`, `client_identifier` em `execution_history` continuam fora de escopo pelo mesmo motivo (FB1). `users` e `user_id` em `execution_history`, removidas em v1.2, **voltam nesta revisão (F12)** com um desenho revisado (perfis N:N em vez de API Key + quota direta) — ver ADR-007 e nota de revisão v1.16 no topo do documento.
>
> A tabela `custom_handlers` também foi removida do schema (revisão v1.9) — a camada de Handlers Python deixou de existir; ver nota de revisão no topo do documento e `PROPOSTA_REVISAO_HANDLERS_E_VOLUME.md`.

---

### 2.3 Formato de `analyses.parameters` e Conversão para JSON Schema MCP

O campo `analyses.parameters` (JSONB, §2.2 Tabela 2) segue um formato fixo por parâmetro:

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

**Módulo compartilhado** (usado por F5 — `list_tools` — e pelo Execution Engine F4, mesma fonte de verdade, sem duplicar regras):
```
schemas/analysis_parameters.py
├─ to_json_schema(parameters: dict) -> dict
│     # usado por F5 (list_tools) — gera o inputSchema padrão MCP
└─ to_pydantic_model(parameters: dict) -> Type[BaseModel]
      # usado pelo Execution Engine (F4) — valida antes de executar
```

**Mapeamento de tipos** (`type` interno → JSON Schema):

| `type` (interno) | JSON Schema `type` | JSON Schema `format` |
|---|---|---|
| string | string | — |
| integer | integer | — |
| number | number | — |
| boolean | boolean | — |
| date | string | date |
| datetime | string | date-time |

> O parâmetro reservado `confirmar_volume_alto` (§3.4) não passa por este módulo — é injetado
> diretamente pelo `mcp_transport/tools.py` no `inputSchema` de toda tool, por ser global.

---

## 3. Fluxos de Dados

### 3.1 Fluxo: Descoberta de Análises

```
┌──────────────────┐
│ Qualquer Cliente │
│ MCP conecta via  │
│ Streamable HTTP         │
└────────┬──────────┘
         │
         ├─ MCP Call: list_tools()
         │
┌────────▼────────────────────────────┐
│   FastAPI MCP Server                │
│  list_tools() endpoint               │
│  ├─ 1. AnalysisService.get_all()   │
│  │    └─ Query: SELECT * analyses   │
│  └─ 2. Retorna JSON schema          │
└────────┬────────────────────────────┘
         │
         ├─ [análise_1, análise_2, ...]
         │
┌────────▼────────────────────────┐
│ Cliente MCP                     │
│ Oferece análises como tools     │
│ "execute_vendas_por_regiao"     │
│ "execute_anomalias_vendas"      │
└─────────────────────────────────┘
```

**Timing:** 1-2 segundos (cold), < 100ms (cache warm)

---

### 3.2 Fluxo: Execução de Análise

> Atualizado pelo F7 (Cache Service) — o cache fica **dentro de
> `AnalysisService.execute()`**, não em `call_tool()` (decisão registrada em
> F7_CACHE_SERVICE.md §3): `execute()` já carrega a análise (id, `updated_at`,
> `cache_frequency`) e atende qualquer chamador (`call_tool` hoje, Celery no
> futuro). `CacheService`/`InMemoryBackend` são instanciados em
> `mcp_transport/tools.py`, no mesmo padrão hoje usado por `VolumeGuardService`.

```
┌──────────────────────────┐
│   Cliente MCP            │
│  Chama: execute_analysis │
│  (id="vendas_por_regiao",│
│   params={mes: "2026-09"})
└─────────┬────────────────┘
          │
┌─────────▼──────────────────────────────────┐
│  FastAPI MCP Server                        │
│  call_tool(name, arguments)                │
│  └─ 1. Resolve análise pelo nome, chama   │
│       AnalysisService.execute() — sem     │
│       lógica de cache aqui                │
│                                             │
│  AnalysisService.execute()                 │
│  ├─ 1. Load analysis (id, updated_at,     │
│  │      cache_frequency)                   │
│  ├─ 2. Valida params (Pydantic)           │
│  ├─ 3. CacheService.resolve_ttl()         │
│  │      └─ inválido → status:error, PARA aqui (nenhuma query) │
│  ├─ 4. cache_frequency="none" → pula direto para o passo 6    │
│  ├─ 5. CacheService.get_or_execute(chave, ttl, confirmar_volume_alto, executor) │
│  │    ├─ Hit dentro do limite → devolve, cached=true, BD intocado │
│  │    ├─ Hit grande sem confirmação → devolve volume_exceeded, cached=false, BD intocado │
│  │    ├─ Hit grande com confirmação → devolve, cached=true + aviso, BD intocado │
│  │    └─ Miss → roda o passo 6 (executor); só grava no cache se "success" │
│  ├─ 6. _run_query() [executor — chamado direto se cache_frequency="none", ou pelo passo 5 em um miss] │
│  │    ├─ Get DataSource config            │
│  │    ├─ Select/reusa Adapter (cacheado por data_source_id) │
│  │    ├─ VolumeGuardService.check_row_count()          │
│  │    │    ├─ Adapter.execute_query(SELECT COUNT(*))  │
│  │    │    └─ Excede limite? → devolve volume_exceeded, PARA aqui │
│  │    ├─ STEP 1 (query)                  │
│  │    │    ├─ Adapter.execute_query()    │
│  │    │    └─ Result: dataset bruto      │
│  │    └─ VolumeGuardService.check_serialized_size()    │
│  │         └─ Excede KB? → devolve volume_exceeded (mesmo com count ok) │
│  └─ 7. (F8, futuro) AuditService.log_execution() — grava também "cached" │
└─────────┬──────────────────────────────────┘
          │
┌─────────▼────────────────────────┐
│   Cliente MCP                    │
│   Recebe resultado               │
│   {status: "success", data: [...], cached: false}│
│   Mostra para o usuário          │
└──────────────────────────────────┘
```

**Timing Total:**
- Leve (< 1s query): 2-5s
- Média (1-5s query): 5-15s
- Pesada (> 5s): async (remoto)

---

### 3.4 Fluxo: Controle de Volume de Dados

Como o servidor não transforma mais os dados (§1, §2.1), o dataset bruto vai
inteiro para o cliente MCP — e um resultado de milhares de linhas pode custar
centenas de milhares de tokens. Esta camada evita isso, em duas etapas:

```
1. Cliente MCP chama execute_analysis(id, params)
2. VolumeGuardService roda um SELECT COUNT(*) barato, com os mesmos filtros
   da query real, ANTES de buscar qualquer dado
   ├─ count > DEFAULT_MAX_RESULT_ROWS → RECUSA (passo 5), nunca busca os dados completos
   └─ count <= DEFAULT_MAX_RESULT_ROWS → segue para o passo 3
3. AnalysisService executa a query completa (STEP 1) e serializa o resultado em JSON
   └─ VolumeGuardService confere o tamanho real em KB — segunda checagem de segurança
      (o count de linhas pode não refletir o tamanho real se as colunas forem muito largas)
4. Se dentro dos dois limites: devolve o dataset bruto normalmente
5. Se qualquer checagem falhar (linhas OU KB) e confirmar_volume_alto=false (default):
   devolve uma resposta estruturada "volume_exceeded" (ver exemplo abaixo),
   sem nunca ter buscado o dataset completo (a menos que a falha tenha sido a de KB,
   caso em que os dados já foram buscados só para medir — ver nota abaixo)
```

> Nota: como a checagem de KB só é possível depois de serializar o resultado, o caso
> "count baixo mas colunas muito largas" busca o dado uma vez para medir e ainda assim
> recusa devolvê-lo ao cliente. É um custo aceito (query já filtrada pelo `COUNT(*)`
> anterior, então o volume de linhas já é baixo) em troca de nunca devolver ao cliente
> um payload maior que o limite configurado.

**Parâmetro reservado `confirmar_volume_alto`** — injetado pelo servidor no JSON Schema
de toda tool MCP (não cadastrado em `analyses.parameters`, é global):
```json
{
  "confirmar_volume_alto": {
    "type": "boolean",
    "required": false,
    "default": false,
    "description": "Confirma execução mesmo que o resultado seja grande (maior consumo de tokens)"
  }
}
```

**Resposta de recusa** (`confirmar_volume_alto=false`, volume acima do limite):
```json
{
  "status": "volume_exceeded",
  "estimativa": { "linhas": 8400, "tamanho_estimado_kb": 510 },
  "limite": { "linhas": 500, "tamanho_kb": 150 },
  "mensagem": "Sua consulta retornaria aproximadamente 8.400 linhas (~510KB), acima do limite de 500 linhas / 150KB. Refine o período ou adicione filtros (ex: região, produto). Se quiser continuar mesmo assim, chame novamente com confirmar_volume_alto=true — atenção: isso pode consumir um volume alto de tokens."
}
```

Se o cliente chamar de novo com `confirmar_volume_alto=true`, o servidor **ignora o
limite** e devolve o dataset completo, incluindo `"aviso": "resultado grande, enviado
por confirmação explícita"` no payload.

**Configuração — 100% via `.env`, sem override por análise:**
```
# .env
DEFAULT_MAX_RESULT_ROWS=500
DEFAULT_MAX_RESULT_SIZE_KB=150
```

Ambos os limites são globais; não há coluna nova em `analyses` para isso, e nenhuma
migration de schema é necessária além da remoção de `custom_handlers` (§2.2).

---

### 3.5 Fluxo: Autenticação e Autorização (F12)

Toda chamada MCP (`list_tools()`/`call_tool()`) chega com o header HTTP
`Authorization: Bearer <token>`, validado antes de qualquer lógica de negócio.
Diferente de um JWT, o token é **opaco** — a validação sempre consulta o BD
(ver ADR-007 para o racional completo dessa escolha).

```
1. Cliente MCP envia Authorization: Bearer <token> em toda requisição ao /mcp
2. AuthService.authenticate(raw_token):
   ├─ hash = sha256(raw_token)
   ├─ AccessTokenRepository.get_by_hash(hash)
   │    └─ não encontrado, revoked_at != NULL, ou expires_at < now() → 401,
   │       PARA aqui (nenhuma query de negócio é feita)
   ├─ UserRepository.get_by_id(token.user_id)
   │    └─ não encontrado ou is_blocked=true → 401, PARA aqui
   ├─ AccessTokenRepository.touch_last_used(token.id) — observabilidade,
   │  não bloqueia o fluxo mesmo se falhar
   └─ Retorna AuthenticatedUser(id, name)

3. list_tools(current_user):
   └─ AnalysisService.get_allowed_analyses(current_user.id)
        └─ SELECT DISTINCT a.* FROM analyses a
           JOIN profile_analyses pa ON pa.analysis_id = a.id
           JOIN user_profiles up    ON up.profile_id  = pa.profile_id
           JOIN profiles p          ON p.id = pa.profile_id
           WHERE up.user_id = :user_id AND a.is_active = true AND p.is_active = true
           -- recalculada a cada chamada — nenhuma permissão fica cacheada no token

4. call_tool(name, arguments, current_user):
   ├─ Resolve a análise pelo nome (igual hoje)
   ├─ REVALIDA a permissão (mesma query do passo 3, filtrada por analysis_id)
   │    └─ análise inexistente/inativa/não permitida para o usuário → status
   │       "error", nunca executa — mesmo se a tool apareceu num list_tools()
   │       anterior (perfil pode ter mudado, ou o usuário foi bloqueado, entre
   │       as duas chamadas)
   └─ AnalysisService.execute(analysis.id, arguments, ..., user_id=current_user.id)
        └─ AuditService.log_execution(..., user_id=current_user.id) — F8 passa
           a registrar quem executou (execution_history.user_id)
```

**Resposta de recusa (401) — genérica, idêntica em todos os casos:**
```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
Content-Type: application/json

{"error": "unauthorized", "message": "Token de acesso inválido ou ausente."}
```
Vale para header `Authorization` ausente ou malformado, token inexistente, expirado,
revogado, e usuário bloqueado ou inexistente — **sem distinguir o motivo** (não vaza se um
token existiu, expirou ou pertence a um usuário bloqueado). Quem precisa saber por que o
acesso falhou é o admin (que consulta o log), não o cliente; o cliente só precisa saber que
deve emitir um novo token em `POST /auth/token`.
A recusa por falta de permissão numa análise (`call_tool()`, passo 4) é outro caso: não é
401 — o usuário está autenticado, e a resposta é o payload MCP `status: "error"`.

**Log de falhas:** como o cliente não vê o motivo, o servidor registra o motivo real
(`WARNING`, `logging` padrão/stdout): `auth_failed reason=<token_expired|token_revoked|token_not_found|
user_blocked|user_not_found|missing_header|malformed_header> client_ip=... token_id=... user_id=...`
no middleware, `access_denied user_id=... analysis_id=... analysis_name=...` em `call_tool()`, e
`login_failed endpoint=... reason=<user_not_found|no_password|wrong_password|user_blocked> client_ip=... user_id=...`
em `/auth/token` e `/auth/revoke`. Nunca loga o token bruto, o header `Authorization`, o hash, a senha,
o `password_hash` nem o e-mail informado. Sem tabela de auditoria de
falhas em V1.0. Detalhes: `features/F12_AUTENTICACAO_PERFIS.md` §4.5.

**Emissão e renovação de token — self-service, fora do fluxo MCP (rotas em `routes/auth.py`, registradas em `main.py`):**
```
POST /auth/token   {"email", "password", "label"?, "expire_days"?}        (TLS obrigatório)
  ├─ email = strip().lower()  →  UserRepository.get_by_external_id(email)
  ├─ bcrypt.checkpw(password, users.password_hash)        -- em thread (CPU-bound)
  │    └─ e-mail inexistente / sem password_hash / senha errada / is_blocked=true
  │       → 401 genérico {"error": "invalid_credentials", "message": "E-mail ou senha inválidos."}
  │         (idêntico nos 4 casos; motivo real só no log; nenhum token é criado)
  ├─ expire_days ausente → ACCESS_TOKEN_EXPIRATION_DAYS; > ACCESS_TOKEN_MAX_EXPIRATION_DAYS → 400
  ├─ token = secrets.token_urlsafe(32)  -- gerado 1x, nunca reconstruído
  ├─ AccessTokenRepository.create(user_id, hash=sha256(token), expires_at, label)
  └─ 200 {"token", "token_type": "Bearer", "expires_at"} — token bruto devolvido 1 única vez

POST /auth/revoke  {"email", "password", "token"}
  ├─ valida e-mail/senha PRIMEIRO (401 igual ao acima)
  ├─ token inexistente ou de outro usuário → 404 {"error": "token_not_found", ...}
  └─ senão revoked_at = now() → 200 {"status": "revoked"}

Renovação: quando o token expira, o usuário chama POST /auth/token de novo e atualiza a
config do cliente MCP. Sem admin no processo, sem tool MCP de renovação (ver ADR-007).
Os dois endpoints ficam FORA do middleware de autenticação do /mcp (não usam Bearer).
Usuários (e-mail em minúsculas + hash bcrypt) continuam cadastrados por INSERT direto, sem CRUD.
```

> **Decisão sobre acesso ao header de autenticação dentro de `list_tools()`/`call_tool()`
> (v1.19):** o SDK `mcp` (`mcp>=1.9.0,<2.0.0`, classe de baixo nível `Server`, ver ADR-006)
> não passa a `Request` HTTP como parâmetro dos decorators. Decidido: **middleware ASGI
> em volta de `/mcp`** (rota exata e mount `/mcp/...`) que valida o token a cada requisição
> — devolvendo 401 HTTP antes de o SDK processar qualquer coisa (o middleware fica dentro do
> `CORSMiddleware`: preflight `OPTIONS` passa sem token e o 401 leva os headers CORS) — e guarda o
> `AuthenticatedUser` num `contextvar` do projeto, lido por `list_tools()`/`call_tool()`.
> Só é seguro porque o transporte é **stateless** (ADR-006, v1.19/v1.21): a task do
> servidor MCP é criada dentro de cada requisição HTTP e herda o `contextvar` gravado pelo
> middleware. **Em stateful isso quebra:** a task é criada uma única vez, no `initialize`,
> e reaproveita o contexto daquela requisição — o handler veria sempre o usuário que abriu
> a sessão, mesmo quando uma requisição posterior traz o token de outro usuário (comprovado
> em teste, ver §14.1 item 8). Trocar para `stateless=False` exige, portanto, abandonar o
> `contextvar` — não é só uma mudança de flag.
> Descartada a alternativa de ler `mcp_server.request_context.request.headers` dentro dos
> handlers (funciona nos dois modos, mas depende de detalhe interno do SDK e só cobre
> `list_tools`/`call_tool`, não a recusa HTTP).

---

## 4. Padrões de Design

### 4.1 Repository Pattern

```python
# Abstração de acesso a dados
class AnalysisRepository:
    async def get_by_id(self, analysis_id: UUID) -> Analysis
    async def get_all(self) -> List[Analysis]
    async def create(self, analysis: AnalysisCreate) -> Analysis
    async def update(self, analysis_id: UUID, data: dict) -> Analysis
    async def delete(self, analysis_id: UUID) -> None

# Implementação
class PostgreSQLAnalysisRepository(AnalysisRepository):
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def get_by_id(self, analysis_id: UUID) -> Analysis:
        result = await self.db.query(
            "SELECT * FROM analyses WHERE id = $1",
            analysis_id
        )
        return Analysis(**result)
```

### 4.2 Factory Pattern (Adapters)

```python
class AdapterFactory:
    _adapters = {
        'postgresql': PostgreSQLAdapter,
        'oracle': OracleAdapter,
        'mysql': MySQLAdapter,
        'sqlserver': SQLServerAdapter,
        'api': APIAdapter
    }

    @classmethod
    def create_adapter(cls, source_type: str, config: dict):
        AdapterClass = cls._adapters.get(source_type)
        if not AdapterClass:
            raise ValueError(f"Adapter '{source_type}' não encontrado")
        return AdapterClass(config)

# Uso
adapter = AdapterFactory.create_adapter('postgresql', config)
data = await adapter.execute_query(sql)
```

### 4.3 Volume Guard (Controle de Volume)

Não é um Registry nem depende de discovery de filesystem/banco — é um serviço leve,
usado diretamente pelo `AnalysisService` dentro do fluxo de execução (ver §3.4):

```python
class VolumeGuardService:
    def __init__(self, max_rows: int, max_size_kb: int):
        self.max_rows = max_rows          # DEFAULT_MAX_RESULT_ROWS (.env)
        self.max_size_kb = max_size_kb    # DEFAULT_MAX_RESULT_SIZE_KB (.env)

    async def check_row_count(self, adapter, count_sql: str, params: dict) -> int:
        count = await adapter.execute_query(count_sql, params, scalar=True)
        if count > self.max_rows:
            raise VolumeExceededError(estimated_rows=count)
        return count

    def check_serialized_size(self, result: list[dict]) -> int:
        size_kb = len(json.dumps(result).encode("utf-8")) / 1024
        if size_kb > self.max_size_kb:
            raise VolumeExceededError(estimated_size_kb=size_kb)
        return size_kb

    def build_refinement_response(self, error: VolumeExceededError) -> dict:
        return {
            "status": "volume_exceeded",
            "estimativa": {"linhas": error.estimated_rows, "tamanho_estimado_kb": error.estimated_size_kb},
            "limite": {"linhas": self.max_rows, "tamanho_kb": self.max_size_kb},
            "mensagem": "...",  # ver §3.4 para o texto completo
        }
```

### 4.4 Strategy Pattern (Execution)

```python
class ExecutionStrategy(ABC):
    @abstractmethod
    async def execute(self, analysis_id, params):
        pass

class InProcessExecutor(ExecutionStrategy):
    async def execute(self, analysis_id, params):
        return await analysis_service._execute_in_process(analysis_id, params)

class AsyncExecutor(ExecutionStrategy):
    async def execute(self, analysis_id, params):
        task = execute_analysis_task.delay(analysis_id, params)
        return {"status": "queued", "task_id": str(task.id)}

executor = InProcessExecutor() if is_light else AsyncExecutor()
result = await executor.execute(analysis_id, params)
```

### 4.5 Token Auth (F12 — ver ADR-007, §3.5)

Sem Registry, sem JWT, sem OAuth client — um módulo leve (`security/token_auth.py`)
com hashing e uma função de autenticação, consultada pelo `AuthService`:

```python
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


@dataclass
class AuthenticatedUser:
    id: UUID   # mesmo tipo de users.id (UUID) e das demais entidades (Analysis.id etc.)
    name: str


class InvalidTokenError(Exception):
    def __init__(self, message: str, reason: str, token_id: UUID | None = None, user_id: UUID | None = None):
        super().__init__(message)          # mensagem genérica, a única que o cliente vê
        self.reason = reason               # AuthFailureReason — só para o log (§3.5)
        self.token_id = token_id
        self.user_id = user_id


async def authenticate(raw_token: str, token_repo, user_repo) -> AuthenticatedUser:
    token = await token_repo.get_by_hash(hash_token(raw_token))
    # Mensagem única e genérica ao cliente em todos os casos de recusa (ver §3.5);
    # o motivo real vai em `reason` (AuthFailureReason) só para o log do servidor.
    generic = "Token de acesso inválido ou ausente."
    if token is None:
        raise InvalidTokenError(generic, reason="token_not_found")
    if token.revoked_at is not None:
        raise InvalidTokenError(generic, reason="token_revoked", token_id=token.id, user_id=token.user_id)
    if token.expires_at < datetime.now(timezone.utc):
        raise InvalidTokenError(generic, reason="token_expired", token_id=token.id, user_id=token.user_id)

    user = await user_repo.get_by_id(token.user_id)
    if user is None:
        raise InvalidTokenError(generic, reason="user_not_found", token_id=token.id, user_id=token.user_id)
    if user.is_blocked:
        raise InvalidTokenError(generic, reason="user_blocked", token_id=token.id, user_id=user.id)

    await token_repo.touch_last_used(token.id)
    return AuthenticatedUser(id=user.id, name=user.name)
```

---

## 5. Stack Técnico

### 5.1 Dependências Principais

```
# requirements.txt

# Web Framework
# Sem versão exata fixada de propósito: no protótipo F0, fixar fastapi==0.104.1 +
# uvicorn[standard]==0.24.0 junto de mcp>=1.2.0 gerou ResolutionImpossible (dependências
# transitivas do mcp exigem fastapi/starlette mais recentes). Deixar o pip resolver a
# versão compatível e travar só o `mcp` (abaixo) evita esse conflito.
fastapi
uvicorn[standard]
pydantic
pydantic-settings

# MCP
mcp>=1.9.0,<2.0.0  # teto obrigatório: a v2.0.0 remove os decorators list_tools()/call_tool()
                    # da classe de baixo nível Server usada no ADR-006 (confirmado no protótipo F0,
                    # que fixou mcp==1.30.0 — última 1.x com essa API)

# Database
asyncpg==0.29.0  # PostgreSQL async driver
oracledb>=2.0.0  # Oracle async driver (thin mode — sem Oracle Client no SO)
aiomysql==0.2.0  # MySQL async driver
aioodbc>=0.4.0   # SQL Server async driver (via ODBC)
pyodbc>=5.2.0    # Driver ODBC nativo, dependência do aioodbc para SQL Server (5.0.1 não tem wheel p/ Python 3.13)
sqlalchemy==2.0.23
alembic==1.13.0

# Data Processing
pandas==2.1.3
numpy==1.26.2

# Async & Caching
redis==5.0.1
aioredis==2.0.1

# Task Queue (Remoto)
celery==5.3.4

# Data Validation
marshmallow==3.20.1

# Logging & Monitoring
python-json-logger==2.0.7
structlog==23.2.0

# Security
cryptography==41.0.7  # Fernet — cifra connection_config.password em repouso (ver §8.2)
bcrypt  # F12 — hash de senha de users.password_hash (versão a fixar na implementação; conferir wheel Python 3.13)

# Utils
python-dotenv==1.0.0
uuid6==1.0.3
```

> ⚠️ **Dependência de SO para SQL Server:** `pyodbc`/`aioodbc` precisam do driver ODBC nativo instalado no sistema (não é só `pip install`) — no Linux/Docker, isso significa instalar o pacote `msodbcsql17` (ou `18`) da Microsoft via `apt` antes de instalar os pacotes Python. Isso entra no `Dockerfile` na F13 (Docker Setup) e é um pré-requisito manual se rodar fora de container.

### 5.2 Python Structure

```
analysis_app/
├── main.py                    # FastAPI app entry point (Streamable HTTP)
├── config.py                  # Configuration (pydantic)
├── requirements.txt
│
├── routes/                    # F12 — rotas HTTP fora do /mcp, registradas em main.py (include_router)
│   ├── __init__.py
│   └── auth.py                # POST /auth/token, POST /auth/revoke (§3.5)
│
├── adapters/
│   ├── __init__.py
│   ├── base.py               # DatabaseAdapter (abstract)
│   ├── postgresql.py
│   ├── oracle.py             # via python-oracledb (thin mode) — sem dependência de SO
│   ├── mysql.py
│   ├── sqlserver.py          # via aioodbc/pyodbc — requer driver ODBC do SO (ver nota abaixo)
│   └── api_adapter.py
│
├── services/
│   ├── __init__.py
│   ├── analysis_service.py   # Core execution logic
│   ├── volume_guard_service.py  # Pré-checagem de linhas/KB (ver §3.4, §4.3)
│   ├── cache_service.py      # Caching logic
│   ├── audit_service.py      # Logging (grava user_id — F12)
│   └── auth_service.py       # F12 — authenticate() + get_allowed_analysis_ids() (§3.5)
│
├── security/
│   ├── __init__.py
│   ├── crypto.py             # Fernet — cifra connection_config.password (já existente)
│   ├── token_auth.py         # F12 — generate_token()/hash_token()/authenticate() (§4.5)
│   ├── password_hash.py      # F12 — verify_password() (bcrypt, em thread) (§4.5)
│   └── auth_middleware.py    # F12 — middleware ASGI do /mcp: 401 + contextvar do AuthenticatedUser (§3.5)
│
├── repositories/
│   ├── __init__.py
│   ├── base.py
│   ├── analysis_repo.py
│   ├── data_source_repo.py
│   ├── execution_repo.py
│   ├── user_repo.py          # F12
│   ├── profile_repo.py       # F12
│   └── access_token_repo.py  # F12
│
├── schemas/
│   ├── __init__.py
│   ├── analysis.py           # Pydantic models
│   ├── data_source.py
│   ├── execution.py
│   ├── analysis_parameters.py  # to_json_schema() / to_pydantic_model() — ver proposta §5
│   └── auth.py                # F12 — AuthenticatedUser e afins
│
├── mcp_transport/             # nome definitivo — "mcp/" colide com o SDK `mcp` importado
│   │                          # dentro do próprio pacote (confirmado na implementação de F1)
│   ├── __init__.py
│   └── tools.py              # MCP tools (list_tools, call_tool) — exigem
│                              # AuthenticatedUser desde F12 (§3.5). resources.py
│                              # (list_resources/read_resource) não existe: fora de
│                              # escopo em V1.0, ver F5_MCP_TOOLS_INTEGRATION.md §3
│
├── scripts/
│   └── encrypt_credential.py     # já existente (não há mais script de emissão de token — F12 usa POST /auth/token)
│
├── database/
│   ├── __init__.py
│   ├── connection.py         # DB connection pool
│   ├── schema.sql            # schema do Config DB, aplicado à mão (F12 acrescenta as tabelas de auth)
│   └── migrations/
│       └── f12_autenticacao.sql  # F12 — CREATE/ALTER para bancos já criados (o projeto não usa Alembic/SQLAlchemy)
│
├── logs/
│   ├── app.log
│   └── audit.log
│
└── tests/
    ├── __init__.py
    ├── test_analysis_service.py
    ├── test_volume_guard_service.py
    ├── test_cache_service.py
    └── fixtures.py
```

---

## 6. Fluxo de Inicialização

### 6.1 Startup (Startup Event)

```
FastAPI Startup (processo uvicorn persistente):
├─ 1. Load config (.env)
│    └─ Inclui DEFAULT_MAX_RESULT_ROWS, DEFAULT_MAX_RESULT_SIZE_KB (VolumeGuardService)
│       e ACCESS_TOKEN_EXPIRATION_DAYS (AuthService, F12 — default aplicado só na
│       emissão de novo token; nenhuma validação de token acontece no startup)
├─ 2. Connect to PostgreSQL (config DB)
├─ 3. Setup connection pools
│    └─ PostgreSQL, MySQL, SQL Server, Oracle, Redis (se ativado)
├─ 4. Initialize CacheService
│    └─ Decide: memory (local) ou Redis (remoto)
├─ 5. Verify all data_sources are reachable
└─ 6. Register MCP endpoints via Streamable HTTP
    ├─ list_tools()
    └─ call_tool()
    (list_resources()/read_resource() fora de escopo em V1.0 — F5)

Total time: 3-5 segundos
```

### 6.2 Shutdown

```
FastAPI Shutdown:
├─ 1. Close all DB connections
├─ 2. Flush cache to disk (se remoto)
├─ 3. Log final entries no histórico de execução
└─ 4. Clean up temp files

Total time: < 1 segundo
```

---

## 7. Decisões Arquiteturais (ADRs)

### ADR-001: FastAPI + MCP (não Flask, não Django)

**Decisão:** Usar FastAPI com MCP SDK
**Razão:**
- ✅ Async/await nativo (melhor para I/O de BD)
- ✅ MCP SDK é otimizado para FastAPI
- ✅ Pydantic built-in (validação tipada)
- ✅ Documentação automática (Swagger)

**Alternativas Rejeitadas:**
- ❌ Django: muito pesado para MCP
- ❌ Aiohttp puro: menos abstrações, mais verboso

---

### ADR-002: Cache Adaptativo (memória local, Redis remoto)

**Decisão:** Não forçar Redis localmente
**Razão:**
- ✅ PostgreSQL em localhost = < 1ms latência
- ✅ Cache em memória é suficiente
- ✅ Zero overhead de rede local
- ✅ Remoto: upgrade para Redis sem mudança de código

---

### ADR-003: Executores Híbridos (in-process + Celery)

**Decisão:** In-process para leves, Celery para pesados (remoto)
**Razão:**
- ✅ Local: zero overhead, resposta rápida
- ✅ Remoto: escalabilidade horizontal
- ✅ Mesmo código em ambos ambientes

---

### ADR-004: PostgreSQL como Config DB

**Decisão:** PostgreSQL dedicado para configurações
**Razão:**
- ✅ Separação: config vs dados de negócio
- ✅ ACID transactions para versionamento
- ✅ Fácil backup e restore
- ✅ Suporta JSONB para flexibilidade

---

### ADR-005: Servidor Entrega Dataset Bruto — Sem Camada de Handlers

**Decisão:** O servidor não transforma mais os dados. Ele executa a query parametrizada
de `analysis_steps` e devolve o resultado bruto (JSON) ao cliente MCP; é o LLM do lado
do cliente quem interpreta, calcula, agrega e visualiza os dados, a cada pedido.
**Razão:**
- ✅ O espaço de perguntas de análise que um usuário pode fazer é infinito ("tendência
  de vendas", "sazonalidade", "correlação entre X e Y") — não é viável pré-programar
  um handler Python para cada tipo de análise possível
- ✅ Qualquer LLM moderno já sabe interpretar, agregar e até gerar gráfico a partir de
  um dataset bruto — reimplementar isso em Python no servidor é trabalho duplicado
- ✅ Reduz drasticamente a superfície de código do servidor (sem Registry, sem discovery
  de filesystem/banco, sem classes de handler para manter)
- ⚠️ Risco introduzido: datasets grandes podem estourar o contexto/custo de tokens do
  cliente — mitigado pelo **Volume Guard** (§3.4, §4.3), que recusa e pede refinamento
  antes de buscar dados demais

**Alternativas Rejeitadas:**
- ❌ Manter Handlers Python (`HandlerRegistry`, discovery built-in + custom): não escala
  para o espaço aberto de análises que os usuários pedem; cada handler novo exigia
  código Python, indo contra o objetivo de "zero código novo por análise" (NEGOCIO.md O1)
- ❌ Handlers "genéricos" configuráveis via JSON (ex.: um handler de agregação
  parametrizável): ainda limitado às operações pré-pensadas; o LLM cliente já faz isso
  sem limite de operações suportadas

**Substitui:** o antigo ADR-005 ("Handlers como Python Classes"), a tabela `custom_handlers`
(removida do schema, §2.2) e o antigo F3 do roadmap ("HandlerRegistry e Discovery"),
agora "Controle de Volume de Resultado" — ver FEATURES_ROADMAP.md v1.6.

---

### ADR-006: MCP via Streamable HTTP com TLS, Agnóstico de Cliente, Sem Autenticação em V1.0

> **Nota (v1.16):** o trecho "sem autenticação" deste ADR-006 descreve a decisão original (V1.0 antes do F12). A partir da revisão v1.16, autenticação por token passou a existir (ver **ADR-007**, a seguir) — o restante da decisão deste ADR-006 (transporte Streamable HTTP, TLS obrigatório, agnóstico de cliente) continua válido sem alteração; só o aspecto "sem autenticação" foi superado.

**Decisão:** Servidor MCP roda como serviço Streamable HTTP persistente na rede interna, com TLS (HTTPS), aceitando qualquer cliente MCP padrão. (Decisão original, V1.0 pré-F12: sem autenticação — ver nota acima.)
**Razão:**
- ✅ Funciona com qualquer cliente MCP (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.) simultaneamente
- ✅ Não fica preso a um único cliente
- ✅ Rede interna é assumida confiável, então autenticação não era necessária na decisão original (revisto pelo ADR-007 — rede confiável reduz risco de rede, mas não substitui saber quem está chamando)
- ✅ Simplifica drasticamente o desenvolvimento inicial
- ✅ TLS é obrigatório **mesmo assim** — não por política de segurança da arquitetura, mas porque clientes MCP reais recusam se conectar a um conector remoto via `http://` simples (confirmado empiricamente no protótipo F0 com Claude Desktop: a conexão TLS era abandonada antes mesmo de chegar uma requisição HTTP ao servidor)

**Alternativas Rejeitadas:**
- ❌ stdio (subprocesso por usuário): não permite múltiplos clientes/usuários na mesma instância compartilhada
- ❌ HTTP+SSE (endpoint `/sse`): transporte usado nas versões 1.0-1.3 deste ADR; substituído por ser a versão anterior/legada do protocolo MCP para transporte remoto — Streamable HTTP é o transporte atual recomendado pela especificação, com endpoint único (`/mcp`) e mesmo modelo de sessão
- ❌ HTTP simples (sem TLS): tecnicamente mais simples e "suficiente" para uma rede interna confiável, mas rejeitado porque, na prática, clientes MCP desktop recusam conectores remotos sem HTTPS — não é uma opção viável mesmo em V1.0
- ❌ Proprietário: dificulta integração com novos clientes
- ❌ Autenticação desde já: complexidade desnecessária para rede confiável (fica para quando o requisito de exposição remota existir — ver §12)

**Consequências práticas confirmadas no protótipo F0 (ver `F0_PROTOTIPO_MCP_MEMORIA.md`):**
- Certificado TLS é dependência obrigatória mesmo em desenvolvimento local — mkcert para gerar um certificado confiável localmente (máquina única); CA interna instalada em cada máquina cliente quando o servidor precisar ser acessado por mais de uma máquina na rede.
- A CLI padrão do uvicorn (`--ssl-certfile`/`--ssl-keyfile`) **não negocia ALPN** — alguns clientes (Chromium/Electron) abandonam a conexão TLS sem nunca enviar uma requisição HTTP se o servidor não participar da negociação ALPN. É necessário configurar um `ssl_context_factory` programático que chame `context.set_alpn_protocols(["http/1.1"])`.
- O endpoint `/mcp`, se montado via `app.mount("/mcp", ...)` do Starlette/FastAPI, responde com redirect `307` para `/mcp/` quando a requisição bate exatamente em `/mcp` sem barra final — o padrão de URL usado por clientes reais. É necessário registrar também uma rota exata (`app.add_route("/mcp", ...)`) para esse caso, evitando o redirect. O próprio `FastMCP` (wrapper de alto nível do SDK, não usado aqui) resolve isso da mesma forma — registrando uma `Route` exata em vez de um `Mount`.
- CORS precisa ser habilitado mesmo sem um navegador tradicional envolvido — clientes desktop (Electron) podem validar o conector via `fetch()` no processo de renderer, sujeito à mesma política de CORS de um browser.

**Consequência adicionada na v1.19 — transporte stateless:**
- O `StreamableHTTPSessionManager` roda com `stateless=True`: cada requisição HTTP cria um transporte novo e não há `Mcp-Session-Id`. Clientes que seguem a especificação simplesmente não reenviam o header (validado no F6 com 2+ clientes MCP reais).
- Custo aceito: o servidor não pode iniciar mensagens por conta própria (notificações, `list_changed`, streaming de progresso). Nenhuma feature atual usa isso — `call_tool()` devolve 1 resultado por chamada.
- Ganho: nenhum estado de conexão entre chamadas, e o `AuthenticatedUser` do F12 (middleware ASGI + `contextvar`, §3.5) fica sempre coerente com a requisição corrente, já que a task do servidor é criada dentro dela e herda seu contexto. *(v1.21)* Este é o **motivo determinante** da escolha: em stateful a task nasce só no `initialize` e o `contextvar` fica congelado no usuário que abriu a sessão (§14.1 item 8). O bloqueio imediato, sozinho, não exigiria stateless — o middleware valida toda requisição nos dois modos.
- Ganhos operacionais: nada guardado em memória por cliente conectado (sem `_server_instances`, sem necessidade de `session_idle_timeout`); restart/deploy sem sessões perdidas (em stateful o cliente receberia 404 e teria de refazer o `initialize`); múltiplas réplicas (V1.2) sem sticky session.
- Custo medido: ~1 ms/req de overhead de transporte a mais que em stateful (sem BD) — irrelevante perto das consultas de autenticação/permissão do F12.
- Cache, `VolumeGuardService` e `AuditService` não mudam (são singletons de módulo em `mcp_transport/tools.py`, sem relação com sessão MCP).
- Rollback: trocar `stateless=True` por `False` **não é seguro com o F12 como está** — o `contextvar` passaria a entregar o usuário errado aos handlers. Exigiria: (1) ler a identidade via `request_context.request` do SDK dentro dos handlers, no lugar do `contextvar`; (2) vincular a sessão ao usuário do `initialize` e recusar requisição com token de outro usuário; (3) configurar `session_idle_timeout`; (4) sticky session em múltiplas réplicas. O teste `test_contextvar_isolated_across_users_in_same_client` (F12 §6.1) falha se a flag for trocada sem essas mudanças.

Detalhes, evidências e receitas de diagnóstico: ver **§14.1**.

**Substitui:** o antigo ADR-008 (Autenticação Multi-User via API Key), removido junto com o serviço correspondente, e revisa a própria decisão de transporte deste ADR-006 (v1.0-1.3: HTTP+SSE → v1.4: Streamable HTTP → v1.5: Streamable HTTP com TLS obrigatório). O número **ADR-007** (antes "Client Identification Automática", removido na v1.2) é reutilizado na revisão v1.16 para uma decisão diferente — **autenticação por token opaco (F12)** — ver a seguir; a decisão de client identification automática (FB1) segue sem ADR, por seguir fora de escopo.

---

### ADR-007: Autenticação por Token Opaco (F12) — Não JWT, Não OAuth2

**Decisão:** Autenticar cada chamada MCP com um **token de acesso opaco** (segredo aleatório gerado com `secrets.token_urlsafe`, hash SHA-256 persistido — nunca o valor bruto). O token é emitido pelo **próprio usuário**, num endpoint HTTP do servidor (`POST /auth/token`) que recebe **e-mail e senha** (hash bcrypt em `users.password_hash`) — sem fluxo OAuth e sem admin no processo. *(Revisão v1.20: a decisão original era emissão administrativa por script, sem login/senha no servidor.)*

**Contexto:** F12 exige saber "quem" está chamando `list_tools()`/`call_tool()`, para filtrar analyses por perfil e negar acesso a usuário bloqueado. Três mecanismos foram avaliados:

| Critério | JWT (self-contained) | OAuth 2.1 (inclusive extensão de autorização do MCP) | Token opaco (escolhido) |
|---|---|---|---|
| Valida sem ir ao BD? | Sim, em teoria — mas ver "Razão" | Não (delegação a authorization server) | Não, sempre consulta o BD |
| Bloqueio de usuário tem efeito imediato? | Só com blacklist adicional (JWT puro não revoga antes do `exp`) | Sim (authorization server pode negar) | Sim, nativo (`is_blocked` checado a cada chamada) |
| Funciona em qualquer cliente MCP sem trabalho extra do cliente? | Sim (é só um header) | Não — exige o cliente implementar o fluxo de autorização OAuth (redirect, PKCE, dynamic client registration); suporte confirmado só em parte dos clientes MCP | Sim (é só um header) |
| Complexidade de implementação no servidor | Média (chave de assinatura, rotação) | Alta (authorization server completo) | Baixa (hash + tabela) |
| Renovação automática sem tocar no cliente | Não (mesmo problema do opaco) | Sim, quando o cliente suporta | Não |

**Razão:**
- ✅ A permissão efetiva (quais analyses um usuário pode ver/executar) depende de `user_profiles`/`profile_analyses`, que podem mudar a qualquer momento — e o requisito de negócio exige que bloquear um usuário tenha efeito **imediato**. Isso força uma consulta ao BD em toda chamada de qualquer forma — a vantagem "stateless" de um JWT (evitar ida ao BD) não se realiza neste projeto, então sua complexidade extra (gestão de chave de assinatura, rotação, blacklist para revogar antes do `exp`) não compra nada em troca
- ✅ OAuth 2.1 resolve delegação de autorização para clientes de terceiros não confiáveis — não é o problema deste projeto (rede interna confiável, ver Restrição T1). Pior: apostar a autenticação nisso acopla o servidor ao cliente MCP mais avançado (confirmado: Claude Desktop suporta a extensão de autorização MCP; não há confirmação equivalente para outros clientes), o que vai contra o pilar "agnóstico de cliente MCP" do projeto (ver NEGOCIO.md §13)
- ✅ Token opaco funciona em qualquer cliente MCP capaz de enviar um header HTTP customizado — praticamente universal, sem exigir que o cliente implemente autorização nenhuma
- ✅ Revogação trivial: `UPDATE access_tokens SET revoked_at = NOW()`, sem blacklist (o usuário revoga o próprio token por `POST /auth/revoke`)
- ✅ (v1.20) Emissão self-service por e-mail/senha: elimina o admin como gargalo e não exige que o usuário tenha acesso ao banco de configuração (um script local exigiria as credenciais do Config DB em cada máquina). A senha nunca sai do hash bcrypt persistido; o segredo que o cliente MCP carrega continua sendo só o token opaco (nunca a senha)

**Alternativas Rejeitadas:**
- ❌ (v1.20) Script local de emissão rodado por cada usuário: obrigaria a distribuir credenciais do Config DB
- ❌ JWT: complexidade de assinatura/rotação sem ganho real de performance (BD já é consultado por causa do bloqueio imediato e das permissões dinâmicas)
- ❌ OAuth 2.1 (inclusive a extensão de autorização MCP para Streamable HTTP): overkill para rede interna confiável; quebra o requisito de "qualquer cliente MCP" por depender de suporte desigual entre clientes ao fluxo de autorização

**Consequências:**
- (v1.20) Emissão e revogação de token são **endpoints HTTP públicos** (`POST /auth/token`, `POST /auth/revoke`, fora do middleware do `/mcp`), protegidos apenas por e-mail e senha sobre TLS — **aumenta a superfície de ataque** em relação à emissão por script: sem rate limit nem bloqueio por tentativas em V1.0 (decisão confirmada; só log — ver F12 §10, item 8), a proteção contra força bruta a senhas é só o custo do bcrypt. Rever antes de qualquer exposição fora da rede interna. Falhas de login retornam sempre o mesmo 401 genérico (sem distinguir e-mail inexistente, senha errada, sem senha ou bloqueado)
- Usuários continuam cadastrados por INSERT direto (sem CRUD), agora com `external_id` (e-mail em minúsculas) e `password_hash`; sem troca/recuperação de senha em V1.0
- `list_tools()`/`call_tool()` sempre fazem 1+ consultas ao BD por chamada — aceitável para o volume de uso deste projeto (rede interna, sem SLA de alta escala)

---

## 8. Considerações de Segurança

### 8.1 Rede Interna, Com Autenticação por Token (V1.0 — F12)

```
✅ Implementar em V1.0:
├─ SQL Injection prevention
│  └─ Parametrized queries ALWAYS
├─ Input validation
│  └─ Pydantic schemas em tudo
├─ Timeout protection
│  └─ Max 60s por query (remoto) / 30s (local)
├─ TLS (HTTPS) obrigatório
│  └─ Requisito de compatibilidade de cliente MCP, não política de segurança em
│     profundidade — clientes MCP reais recusam conector remoto via http:// simples,
│     mesmo em rede interna confiável (ver ADR-006, §7)
├─ CORS habilitado (CORSMiddleware)
│  └─ Clientes desktop podem validar o conector via fetch() no processo de
│     renderer, sujeito à mesma política de CORS de um browser (ver ADR-006, §7)
├─ Autenticação por token de acesso (F12, ADR-007)
│  └─ Token opaco (hash SHA-256), usuário bloqueado perde acesso imediato,
│     sem OAuth2/SSO/JWT — ver §3.5
├─ Controle de acesso via perfis (F12, RBAC básico)
│  └─ Usuário → perfil → analyses (N:N); permissão recalculada a cada chamada,
│     nunca cacheada no token
└─ Log de execução
   ├─ O quê (qual análise) foi executado
   ├─ Quando (timestamp)
   ├─ Quem (execution_history.user_id, F12)
   └─ Resultado (success/fail)

❌ Não implementar em V1.0 (rede privada confiável):
├─ Identificação de qual cliente MCP/software está chamando (FB1 — diferente
│  de identificação de usuário, já implementada via F12)
├─ Rate limiting / quotas por usuário
└─ SSO/LDAP/OAuth (avaliado e descartado para V1.0 — ver ADR-007)

⚠️ Futuro (quando expor remotamente ou sair da rede confiável — V1.1+):
├─ Reintroduzir ClientIdentificationService (qual cliente MCP)
├─ Rate limiting mais rigoroso
├─ IP whitelist
└─ SSO/LDAP/Azure AD (reavaliar OAuth2, descartado só para o contexto de V1.0 — ver ADR-007)
```

### 8.2 Credenciais de BD

```
✅ Armazenar:
├─ connection_config em JSONB (campo `password` e demais credenciais cifrados
│  com Fernet — biblioteca `cryptography` do Python — antes de persistir)
├─ Usar .env para secrets (Docker)
└─ Log de execução como trilha de acesso

Exemplo .env:
POSTGRES_CONFIG_PASSWORD=secure_password
FERNET_KEY=<chave gerada com Fernet.generate_key(), fora do repositório>
ACCESS_TOKEN_EXPIRATION_DAYS=90       # F12 — validade padrão de novos tokens (POST /auth/token sem expire_days)
ACCESS_TOKEN_MAX_EXPIRATION_DAYS=365  # F12 — maior expire_days aceito em POST /auth/token (acima → 400)
```

**Formato de `data_sources.connection_config`** (ver §2.2, Tabela 1 — antes um placeholder):
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

---

## 9. Plano de Implantação

### 9.1 Local (Desenvolvimento)

```bash
# Preparar
git clone <repo>
cd analysis_app
cp .env.example .env

# Certificado TLS local (obrigatório — ver ADR-006):
brew install mkcert && mkcert -install
mkcert -cert-file certs/server.pem -key-file certs/server-key.pem localhost 127.0.0.1 <ip-da-maquina>

# Config DB: PostgreSQL rodando e com database/schema.sql aplicado.
# (docker-compose local/remoto entra com a F13 — Docker Setup.)

# Subir o servidor (HTTPS com ALPN — ver aviso ao final desta seção):
python run_https.py

# Verificar
curl https://localhost:3000/health

# Emitir um token de acesso (F12 — ver §3.5, ADR-007) — o próprio usuário, com e-mail e senha:
curl -X POST https://localhost:3000/auth/token -H "Content-Type: application/json" \
     -d '{"email": "maria@empresa.com", "password": "...", "label": "Claude Desktop", "expire_days": 90}'

# Configuração em cada cliente MCP (exemplo genérico, formato varia por app):
# {
#   "mcpServers": {
#     "analysis": {
#       "url": "https://<ip-da-maquina>:3000/mcp",
#       "headers": { "Authorization": "Bearer <token gerado acima>" }
#     }
#   }
# }
#
# Repita a mesma URL em Claude Desktop, Gemini Desktop, OpenAI Desktop, etc. —
# cada usuário/cliente com seu próprio token (F12 permite N tokens por usuário).
# HTTPS é obrigatório (ver ADR-006): clientes MCP reais recusam conector remoto
# via http:// simples, mesmo em rede interna confiável. Se o cliente estiver em
# outra máquina, instale a CA do mkcert (`mkcert -CAROOT`) nela antes de confiar
# no certificado.
#
# ⚠️ Subir o servidor apenas com `uvicorn --ssl-certfile=... --ssl-keyfile=...`
# não basta: a CLI do uvicorn não negocia ALPN, e alguns clientes (Chromium/Electron)
# abandonam a conexão TLS sem nunca enviar uma requisição HTTP. É necessário um
# `ssl_context_factory` programático chamando `context.set_alpn_protocols(["http/1.1"])`
# (ver protótipo F0, `run_https.py`).
```

**Tempo de setup:** 5-10 minutos

### 9.2 Produção Interna (nginx + Certbot)

Ainda dentro de V1.0 — rede interna, sem exposição pública (Restrição T1) — mas num servidor dedicado em vez da máquina de desenvolvimento. Aqui, **nginx** faz a terminação TLS como reverse proxy na frente do FastAPI/uvicorn, que passa a rodar atrás dele em HTTP simples. Isso elimina a necessidade do `ssl_context_factory`/ALPN manual da seção 9.1: o OpenSSL do nginx já negocia ALPN nativamente, então esse workaround é específico do cenário "uvicorn falando TLS diretamente" (dev com mkcert), não de produção com nginx.

```nginx
# /etc/nginx/sites-available/analysis-mcp
server {
    listen 443 ssl;
    server_name analise.empresa.internal;

    ssl_certificate     /etc/letsencrypt/live/analise.empresa.internal/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/analise.empresa.internal/privkey.pem;

    location /mcp {
        proxy_pass http://127.0.0.1:3000/mcp;
        proxy_http_version 1.1;
        proxy_set_header Connection "";   # necessário para o streaming (SSE) do Streamable HTTP
        proxy_buffering off;
        proxy_set_header Host $host;
    }

    location /health {
        proxy_pass http://127.0.0.1:3000/health;
    }
}
```

**Certificado via Certbot — duas opções, a escolher quando o servidor de produção for provisionado:**

**Opção A — DNS-01 com domínio público (se a operação já tiver domínio + acesso à API do provedor de DNS):**
```bash
certbot certonly --dns-<provedor> \
  --dns-<provedor>-credentials /etc/letsencrypt/<provedor>.ini \
  -d analise.empresa.internal
# renovação automática via cron/systemd timer do próprio certbot
```
Não exige expor o servidor à internet — o desafio DNS-01 só cria um registro TXT no DNS **público** do domínio; o hostname em si pode continuar resolvendo só internamente (DNS split-horizon).

> **Confiança do cliente: nenhuma configuração extra.** O certificado é assinado pela CA do Let's Encrypt, que já vem pré-instalada por padrão em todo sistema operacional, navegador e runtime (macOS, Windows, Linux, Node.js, etc.) — exatamente como qualquer certificado de uma API pública comum. Nenhum cliente MCP precisa instalar ou confiar em nada; a URL `https://analise.empresa.internal:3000/mcp` funciona de imediato, do mesmo jeito que funcionaria acessando qualquer site HTTPS público.

**Opção B — CA interna própria (sem depender de domínio público):**
```bash
certbot certonly --server https://sua-ca-interna.empresa.internal/acme/directory \
  -d analise.empresa.internal
```
Certbot suporta qualquer servidor compatível com ACME via `--server`, não só o Let's Encrypt — uma CA interna (ex.: `step-ca`) resolve isso sem tocar em DNS público.

> **Confiança do cliente: mesma exigência do mkcert (seção 9.1).** Essa CA interna é privada — não está pré-instalada em lugar nenhum, então nenhum cliente confia nela por padrão. É necessário instalar/confiar nessa CA em cada máquina cliente antes de conseguir se conectar via HTTPS (import do certificado raiz no Keychain/Certificate Store/`ca-certificates`, conforme o SO). A vantagem sobre o mkcert é só a renovação centralizada e automática pelo Certbot, em vez de manual por máquina — mas o ônus de confiança client-side é o mesmo.

> **Resumindo a diferença entre as opções:** o que exige (ou não) tocar em cada cliente não é "nginx+Certbot vs. mkcert" — é se o certificado é assinado por uma CA pública já confiável de fábrica (Opção A) ou por uma CA privada que só existe porque você a criou (Opção B e mkcert). Nenhuma das duas opções muda o resto da arquitetura: o app continua servindo em `/mcp` com autenticação por token (ADR-007) independente da origem do certificado — só a origem/renovação do certificado, e a necessidade (ou não) de configurar os clientes quanto à CA, mudam.

### 9.3 Remoto (Produção — Futuro)

```bash
docker build -t analysis-mcp:1.0 .
docker tag analysis-mcp:1.0 registry.company.com/analysis-mcp:1.0
docker push registry.company.com/analysis-mcp:1.0

kubectl create namespace analysis
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

kubectl get pods -n analysis
kubectl logs -n analysis <pod-name>
```

> ⚠️ Antes deste passo, reintroduzir autenticação (ver §7 ADR-006 e §12).

---

## 10. Monitoramento e Observabilidade

### 10.1 Métricas

```python
from prometheus_client import Counter, Histogram

analysis_executions = Counter(
    'analysis_executions_total',
    'Total de execuções',
    ['analysis_id', 'status']
)

execution_duration = Histogram(
    'analysis_execution_seconds',
    'Duração da execução',
    ['analysis_id']
)

cache_hits = Counter(
    'cache_hits_total',
    'Hits no cache',
    ['analysis_id']
)
```

### 10.2 Logging

> **Estado atual (F7, ajuste retroativo 2026-09-27):** o design abaixo (`structlog`, evento estruturado `analysis_executed`) é o alvo, a formalizar no F8 (Log de Execução) junto de `execution_history`. Hoje existe só um setup mínimo com o `logging` da stdlib — `main.py` chama `logging.basicConfig(level=logging.INFO, ...)`, e `services/cache_service.py`/`services/analysis_service.py`/`mcp_transport/tools.py` emitem `logger.info()`/`logger.warning()` simples (texto, não estruturado) para as decisões de cache (`Cache HIT`/`Cache MISS`/bypass/backend ativo) — ver F7_CACHE_SERVICE.md §8.4. Sem esse `basicConfig`, nenhum desses logs aparecia no console, porque o root logger fica em `WARNING` por padrão e o uvicorn só configura os loggers `uvicorn.*`.

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "analysis_executed",
    analysis_id=str(analysis_id),
    version=version_id,
    status="success",
    execution_time_ms=1234,
    cached=False
)
```

### 10.3 Health Check

```python
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "db": await check_postgres(),
        "cache": await check_cache(),
        "volume_limits": {"max_rows": settings.DEFAULT_MAX_RESULT_ROWS, "max_size_kb": settings.DEFAULT_MAX_RESULT_SIZE_KB},
        "analyses": await AnalysisService.count()
    }
```

---

## 11. Diagrama de Sequência (Caso de Uso Principal)

```
Cliente MCP       FastAPI Server    PostgreSQL              Cache
    │                 │                 │                      │
    │ list_tools()   │                 │                      │
    ├────────────────>│                 │                      │
    │                 │ SELECT analyses │                      │
    │                 ├────────────────>│                      │
    │                 │<────────────────┤                      │
    │<────────────────┤ [análise_1, análise_2, ...]            │
    │                 │                 │                      │
    │ execute_analysis│                 │                      │
    ├────────────────>│                 │                      │
    │                 │ get_or_execute  │                      │
    │                 ├─────────────────────────────────────────>│
    │                 │<─────────────────────────────────────────┤ cache miss
    │                 │ SELECT steps    │                      │
    │                 ├────────────────>│                      │
    │                 │<────────────────┤                      │
    │                 │ SELECT COUNT(*) (Volume Guard pré-check)│
    │                 ├────────────────>│                      │
    │                 │<────────────────┤ excede limite? recusa aqui
    │                 │ execute query (dataset bruto)          │
    │                 ├────────────────>│                      │
    │                 │<────────────────┤                      │
    │                 │ set cache       │                      │
    │                 ├─────────────────────────────────────────>│
    │                 │ log execution   │                      │
    │                 ├────────────────>│                      │
    │<────────────────┤ result (JSON, dataset bruto)            │
    │                 │                 │                      │
```

---

## 12. Roadmap Arquitetural

```
V1.0 (MVP Local):
├─ MCP via Streamable HTTP, com autenticação por token opaco + perfis (F12, ADR-007)
├─ Multi-cliente simultâneo (Claude Desktop, Gemini Desktop, OpenAI Desktop, etc.),
│  cada um com seu próprio token
└─ Log de execução com identificação de usuário (execution_history.user_id)

V1.1 (Identificação de Cliente + Rate Limiting — quando necessário):
├─ ClientIdentificationService: qual cliente MCP/software executou (FB1)
├─ Rate limiting / quotas por usuário (FB3)
├─ SSO/OAuth (Azure AD, Google, LDAP — FB5), se a plataforma sair da rede confiável
├─ Necessário antes de expor além da rede confiável
└─ Especificação técnica de FB1 já existe e pode ser retomada

V1.2 (Production Remoto):
├─ Redundância e failover
├─ Load balancing
├─ Kubernetes deployment
└─ Dashboard de uso

V2.0 (Ecosystem):
├─ Qualquer cliente MCP (aberto)
├─ Marketplace compartilhado
├─ Multi-tenant (múltiplas orgs)
└─ MCP como padrão de facto
```

---

## 13. Decisão de Tecnologias

| Componente | Tecnologia | Justificativa |
|-----------|-----------|---------------|
| **Web Framework** | FastAPI | Async nativo, MCP SDK support, Streamable HTTP |
| **Config DB** | PostgreSQL | JSONB, ACID, versionamento |
| **Data Sources** | PostgreSQL, MySQL, SQL Server, Oracle, API | Adaptadores agnósticos |
| **Cache (Local)** | Memória + Dict | Zero overhead, suficiente |
| **Cache (Remoto)** | Redis | Distributed, cluster-ready |
| **Task Queue** | Celery | Escala horizontal, remoto |
| **Controle de Volume** | VolumeGuardService (COUNT(*) + checagem de KB) | Evita estourar tokens do cliente, sem handler nenhum |
| **Autenticação** | Token opaco (hash SHA-256), sem JWT/OAuth2 | Bloqueio imediato e permissões dinâmicas já exigem BD por chamada — ver ADR-007 |
| **Containerização** | Docker | Portabilidade local ↔ remoto |
| **Orchestração** | Docker Compose (local), Kubernetes (remoto) | Simplicity + power |

---

## 14. Prototipagem e Proof of Concept

### Sprint 0 (Protótipo — 1 semana)

```
├─ FastAPI hello world (Streamable HTTP)
├─ 1 PostgreSQL adapter
├─ VolumeGuardService básico (checagem de linhas)
├─ 1 análise de exemplo
├─ MCP list_tools() + call_tool()
├─ 2 clientes MCP diferentes conectados simultaneamente
└─ Análise executando e retornando dados para ambos
```

**Sucesso:** pedir "Mostre vendas de setembro" em dois clientes MCP diferentes (ex.: Claude Desktop e Gemini Desktop), ao mesmo tempo, e receber dados reais do BD local em ambos.

### 14.1 Lições Técnicas do Protótipo F0

Consolidadas a partir do antigo `mcp_prototype/README.md` (o protótipo continua no repositório como referência executável; a análise de "por quê" mora aqui). Resumo das decisões: ADR-006 (§7).

**1. ALPN: por que existe `run_https.py` e não `uvicorn --ssl-keyfile/--ssl-certfile`**
- Sintoma: certificado válido, `curl` e o SDK cliente do `mcp` funcionavam, mas o Claude Desktop reportava "nenhum servidor respondeu" e **nenhuma requisição aparecia no log** — a conexão TLS era abandonada antes da camada HTTP.
- Diagnóstico: `openssl s_client -alpn h2,http/1.1 -connect 127.0.0.1:3000` retornava "No ALPN negotiated" — a CLI do uvicorn não negocia ALPN.
- Correção: subir o uvicorn programaticamente com `ssl_context_factory` chamando `context.set_alpn_protocols(["http/1.1"])` (implementado em `run_https.py`).
- Escopo: o workaround é específico do cenário "uvicorn falando TLS direto" (dev/mkcert). Atrás de nginx (§9.2) o OpenSSL do nginx já negocia ALPN.

**2. Rota exata `/mcp` (`_MCPExactPathASGI`) além do `app.mount("/mcp", ...)`**
- O `Mount` do Starlette só casa com `/mcp/<algo>`. Uma requisição em `/mcp` exato (sem barra final) recebe `307 Temporary Redirect` para `/mcp/`.
- O Claude Desktop configura e usa a URL **sem barra final**, e não há garantia de que o cliente siga redirect em `POST`/`DELETE`. Com a rota exata (`app.add_route("/mcp", ...)`, registrada antes do `mount`), 100% do tráfego de uma sessão real (11 `POST`, 3 `GET`, 3 `DELETE`) bateu em `/mcp` sem nenhum `307`.
- Por que uma classe com `__call__` e não uma função: o Starlette trata funções passadas a `add_route` como `func(request) -> Response`; `handle_request` é ASGI puro `(scope, receive, send)`. Um objeto chamável escapa dessa checagem.
- O próprio `FastMCP` (não usado aqui — ADR-006) resolve o mesmo problema registrando uma `Route` exata, não um `Mount`.

**3. Versão do SDK `mcp`**
- `mcp>=1.9.0,<2.0.0`: a partir da 2.0.0 o SDK removeu os decorators `@server.list_tools()`/`@server.call_tool()` da classe de baixo nível `Server`. O protótipo fixou `mcp==1.30.0` (última 1.x com essa API). Ver §5.1.

**4. Certificado TLS (mkcert)**
- Máquina única: `mkcert -install` + `mkcert localhost 127.0.0.1 ::1`. Nunca versionar a chave privada (`certs/` no `.gitignore`).
- Cliente em outra máquina: gerar o certificado também para o IP/hostname do servidor (`mkcert <ip> <hostname>`) e instalar a CA (`mkcert -CAROOT`) na máquina do cliente.

**5. Como cada tipo de cliente/teste confia na CA**
- Claude Desktop/ChatGPT Desktop: usam o armazenamento do SO (após `mkcert -install`).
- Claude Code (CLI Node.js): pode não confiar no armazenamento do SO como o `curl` — usar `export NODE_EXTRA_CA_CERTS="$(mkcert -CAROOT)/rootCA.pem"` em vez de desabilitar a validação TLS.
- Script Python (httpx/certifi): `SSL_CERT_FILE="$(mkcert -CAROOT)/rootCA.pem" python seu_script.py`. O `curl` não precisa (usa o armazenamento do SO).

**6. Registrar o servidor no Claude Code**
- `claude mcp add --transport http <nome> https://<host>:3000/mcp` — `http` é o transporte genérico para conexões remotas (cobre HTTP/HTTPS e Streamable HTTP); não existe um valor `streamable-http` separado. Escopos: `--scope local` (padrão), `project` (`.mcp.json` versionado) e `user`. Verificação: `claude mcp list`, `claude mcp get <nome>`, `/mcp`.

**7. Validar multi-cliente sem clientes desktop**
- Abrir duas sessões independentes com `mcp.client.streamable_http` contra o mesmo `/mcp`, chamando `list_tools()`/`call_tool()` em cada uma — foi assim que o protótipo foi validado durante o desenvolvimento (base do F6).

**8. Transporte stateless e `contextvar` (análise de 2026-09-30, F12)**
- Sintoma que evitamos: com `stateless=False`, um middleware ASGI que grava o usuário autenticado num `contextvar` antes de `session_manager.handle_request()` **valida** o token de cada requisição, mas o handler `list_tools()`/`call_tool()` enxerga sempre o usuário do `initialize`.
- Causa: em stateful o `StreamableHTTPSessionManager` inicia a task do servidor uma única vez (`self._task_group.start(run_server)` no `initialize`) e a guarda em `_server_instances`; as mensagens seguintes só são entregues a ela, que mantém o contexto copiado da primeira requisição. Em stateless, `_handle_stateless_request` inicia uma task nova por requisição, com o contexto dela.
- Evidência (SDK `mcp` 1.27): `initialize` como MARIA + `tools/list` com tokens de JOAO e de um usuário bloqueado → em stateful o handler viu MARIA nas três; em stateless viu o usuário correto em cada uma. `mcp_server.request_context.request` mostrou o header correto nos dois modos.
- Consequência: `stateless=True` é pré-requisito do desenho do F12 (§3.5). Custo medido: ~3,0 ms/req em stateless contra ~2,0 ms/req em stateful (só transporte).

---

**Documento de Arquitetura Completo.**
**Pronto para começar desenvolvimento.**
