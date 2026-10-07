# [F15] Performance Optimization

## Feature Spec

**ID:** F15
**Nome:** Performance Optimization — pool PostgreSQL configurável, benchmark das metas de RNF1 e otimização medida do Config DB
**Prioridade:** 🟠 Alta
**Esforço Estimado:** 2d (16h)
**Status:** 🟩 Done (2026-10-07) — pendências menores em §12

> **Origem dos requisitos:** FEATURES_ROADMAP.md (linha da F15), NEGOCIO.md RNF1 (Performance), RNF3 (Escalabilidade) e RNF4 (10+ clientes simultâneos), e as pendências deixadas pelas specs F7, F11 (§10 #7) e F14 (§11 #4). O escopo foi decidido item a item com o usuário em 2026-10-05 (§10). O roadmap só tinha uma linha para a F15.

---

## 1. Visão
Medir antes de otimizar. A F15 entrega um benchmark reproduzível das metas de RNF1, torna configurável o pool do PostgreSQL (hoje fixo no padrão do asyncpg) e corta custo do Config DB no caminho de cada chamada `/mcp`, **sem enfraquecer** a revogação imediata de token e de permissão da F12.

## 2. Objetivo
Ter números de baseline e de "depois" para as metas de RNF1, e só mudar código onde a medição mostrar ganho.

**Métrica de Sucesso:**
- ✅ Existe um benchmark reproduzível que mede: cache hit (<100ms), `COUNT(*)` do Volume Guard (<500ms), `list_tools` (<2s) e análise leve (<5s), e imprime baseline vs. depois
- ✅ O tamanho do pool PostgreSQL é configurável pelo `.env`; sem as variáveis, o comportamento é idêntico ao atual (`min_size=max_size=10`)
- ✅ Nenhuma mudança enfraquece o bloqueio de usuário, a revogação de token ou a mudança de perfil (continuam valendo na próxima chamada — F12 / ADR-007)
- ✅ Cada índice novo é justificado por `EXPLAIN ANALYZE` (sem índice "por precaução")
- ✅ O script de carga sustenta 10+ clientes simultâneos sem erro em `execution_history` e sem esgotar o pool
- ✅ A suíte existente (480 testes) continua 100% verde; o benchmark e o script de carga ficam fora dela

## 3. Contexto
**Depende de:** F7 (Cache Service), F2 (PostgreSQL Adapter), F12 (autenticação — caminho medido), F14 (retry/timeout — comportamento preservado)
**É dependência de:** F17 (Unit Tests), F18 (Integration Tests), F16 (API Documentation, se citar as metas)

**Pendências herdadas que esta feature resolve:**
- F11 §10 #7 / F14 §11 #4: o `PostgreSQLAdapter` usa os defaults do asyncpg (`min_size=max_size=10`) por data source.

**Fora do escopo — decidido (§10):** log assíncrono do `execution_history`, `sslmode` ignorado por PostgreSQL/MySQL (F11 #1), `translate_params` com `::nome`/literais (F11 #5) e análises assíncronas com status check.

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
Componentes que serão criados/modificados:
├─ adapters/postgresql.py        (modif.)  → connect() passa min_size/max_size ao create_pool
├─ config.py                     (modif.)  → PG_POOL_MIN_SIZE / PG_POOL_MAX_SIZE (+ validação no startup)
├─ database/connection.py        (modif.)  → Config DB com pool próprio (CONFIG_DB_POOL_*) — ver §11 #1
├─ database/schema.sql           (modif.)  → só os índices que o EXPLAIN ANALYZE justificar (§4.4)
├─ scripts/benchmark.py          (novo)    → mede as 4 metas de RNF1; grava baseline em JSON
├─ scripts/load_test.py          (novo)    → 10+ clientes simultâneos / volume de execuções
├─ .env.example, docker-compose.{local,remote,dist}.yml (modif.) → novas variáveis
└─ tests/test_postgresql_adapter.py, tests/test_config.py (modif.) → pool configurável e validação
```
`cache_service.py`, `cache_backend.py` e `audit_service.py` **não** entram — só mudam se o benchmark provar um problema (§4.5).

### 4.2 Diagnóstico do caminho atual (lido no código em 2026-10-05)
Round-trips ao Config DB numa chamada `call_tool` com **cache hit**:
```
AuthMiddleware → AuthService.authenticate()
   1. access_tokens  SELECT por token_hash        (access_token_repo.get_by_hash)
   2. users          SELECT por id                (user_repo.get_by_id)
   3. access_tokens  UPDATE last_used_at          (touch_last_used — ESCRITA a cada chamada)
call_tool()
   4. analyses       SELECT por name              (analysis_repo.get_by_name)
   5. perfis         SELECT ... JOIN x3           (profile_repo.get_allowed_analysis_ids)
AnalysisService.execute()
   6. analyses       SELECT por id                (analysis_repo.get_by_id — repete o 4)
   7. execution_history INSERT                    (audit_service.log_execution)
```
- **≥ 7 idas ao Config DB mesmo com cache hit** (o hit só evita o data source). `list_tools` faz 3 (auth) + 1 (JOIN de permissão) = 4.
- O Config DB usa a mesma classe `PostgreSQLAdapter`, logo o mesmo pool de 10 conexões — é o recurso mais disputado com 10+ clientes (RNF4).
- Indexação já existente (schema.sql): `token_hash` UNIQUE, PKs de `users`/`analyses`, `analyses.name` UNIQUE, PK composta de `user_profiles (user_id, profile_id)` e `profile_analyses (profile_id, analysis_id)`. À primeira vista as queries estão cobertas; **é provável que quase nenhum índice novo seja necessário** — o `EXPLAIN ANALYZE` decide.

### 4.3 Pool PostgreSQL configurável
```python
# adapters/postgresql.py
self._pool = await asyncpg.create_pool(
    host=..., port=..., user=..., password=..., database=...,
    command_timeout=settings.query_timeout_seconds,
    min_size=self.config.get("pool_min_size", settings.pg_pool_min_size),
    max_size=self.config.get("pool_max_size", settings.pg_pool_max_size),
)
```
- Padrão `PG_POOL_MIN_SIZE=10` / `PG_POOL_MAX_SIZE=10` = comportamento atual (sem surpresa em instalações existentes).
- Validação no startup (`config.py`, como as demais): `MIN >= 1`, `MAX >= MIN`; valor inválido falha com mensagem clara.
- Chaves opcionais no `connection_config` do data source (`pool_min_size`/`pool_max_size`) sobrepõem o padrão **por data source**, sem mexer em Python. Só o PostgreSQL (MySQL, SQL Server e Oracle ficam como estão).
- Config DB: pool próprio via `CONFIG_DB_POOL_MIN_SIZE/MAX_SIZE` (§11 #1).

### 4.4 Benchmark (`scripts/benchmark.py`)
Roda contra o ambiente local (compose + `.env`), com uma análise leve semeada. Mede, com N repetições e percentis (p50/p95/máx):
```
cache hit      → execute() da mesma análise/params 2x; mede a 2ª            (meta < 100ms)
COUNT(*)       → volume_guard.check_row_count() isolado                      (meta < 500ms)
list_tools     → list_tools(user) completo, incluindo auth                   (meta < 2s)
análise leve   → call_tool() com cache miss (cache_frequency='none')         (meta < 5s)
auth           → AuthService.authenticate() isolado (3 idas ao Config DB)    (referência)
```
- Saída: tabela no terminal + `benchmark-<data>.json` (fora do git). Flag `--compare <baseline.json>` mostra a variação.
- **A baseline é rodada ANTES de qualquer mudança** e o resultado vai para a §10 desta spec.
- Mede também `EXPLAIN (ANALYZE, BUFFERS)` das queries de §4.2 (5 e `get_allowed_for_user`) com volume realista (100+ análises, muitos perfis — RNF3); índice novo só entra se a query fizer `Seq Scan` com custo relevante.
- Candidatos a índice, **condicionados à medição**: `profile_analyses(analysis_id)` e `user_profiles(profile_id)` (buscas reversas). Cada índice acrescenta custo de escrita; `execution_history` já tem 3.

### 4.5 Medições que só viram código se provarem problema
| Item | O que medir | Só altera código se |
|---|---|---|
| `touch_last_used` (UPDATE a cada chamada) | custo da escrita e contenção de lock em 10+ clientes com o mesmo token | for gargalo — a opção seria gravar só se `last_used_at` tiver mais de N minutos (não toca em revogação). Ver §11 #2 |
| Cache F7 (RNF3) | taxa de hit sob carga repetida (< 1% das queries ao BD), memória com `CACHE_MAX_SIZE_MB`, custo do `tamanho_kb` e do lock por chave | taxa de hit ou memória fora da meta |
| `get_by_name` + `get_by_id` (2 SELECTs de `analyses`) | se o segundo é custo mensurável | merecer reaproveitar a análise já carregada (mudaria a assinatura de `execute()` — §11 #3) |

**Não entra, em nenhuma hipótese, cache de token ou de permissões** (decisão §10 #3): a F12 exige que bloqueio, revogação e troca de perfil valham na chamada seguinte (ADR-007; `is_analysis_allowed` já documenta "sem cache").

### 4.6 Teste de carga (`scripts/load_test.py`)
Script manual (fora do pytest), via `asyncio` + cliente MCP real/HTTP contra o servidor local:
```
python scripts/load_test.py --clients 10 --duration 60 --token-file secrets/admin-token.txt
```
- 10+ clientes simultâneos executando mix de análises (hit e miss); relata erros, p95 e esgotamento de pool.
- Verificação final: **100% das execuções gravadas** em `execution_history` (RNF4) e nenhum erro de concorrência.
- Projeção para "1000+ execuções/dia" = ~0,012 req/s médio; o teste valida o **pico** (10+ simultâneos), não o volume diário.

### 4.7 Banco de Dados
Sem tabelas novas. Só índices **se** a §4.4 os justificar:
```sql
-- exemplo condicionado ao EXPLAIN ANALYZE (não aplicar sem a evidência)
CREATE INDEX idx_profile_analyses_analysis ON profile_analyses(analysis_id);
CREATE INDEX idx_user_profiles_profile ON user_profiles(profile_id);
```
Bancos existentes não rodam o `schema.sql` de novo: se houver índice novo, registrar o `CREATE INDEX IF NOT EXISTS` para rodar na mão (mesmo aviso da coluna `error_code` da F14).

### 4.8 Interfaces
Nenhuma interface MCP muda. Contrato de resposta (`success` / `volume_exceeded` / `error` + `error_code`) e `cached` ficam idênticos.

## 5. Critérios de Aceitação
```gherkin
Feature: Performance Optimization

Scenario: Pool com o padrão
  Given PG_POOL_MIN_SIZE e PG_POOL_MAX_SIZE ausentes do .env
  When um PostgreSQLAdapter conecta
  Then o pool nasce com min_size=10 e max_size=10 (comportamento atual)

Scenario: Pool configurado pelo .env
  Given PG_POOL_MIN_SIZE=2 e PG_POOL_MAX_SIZE=5
  When um PostgreSQLAdapter conecta
  Then o pool nasce com min_size=2 e max_size=5

Scenario: Pool por data source
  Given connection_config com pool_max_size=3
  When o adapter do data source conecta
  Then o pool desse data source tem max_size=3 e os demais mantêm o padrão do .env

Scenario: Configuração de pool inválida
  Given PG_POOL_MAX_SIZE menor que PG_POOL_MIN_SIZE
  When a aplicação sobe
  Then falha no startup com mensagem clara

Scenario: Benchmark com comparação
  Given uma baseline salva antes das mudanças
  When scripts/benchmark.py roda com --compare
  Then imprime p50/p95 de cada meta de RNF1 e a variação contra a baseline

Scenario: Revogação continua imediata
  Given um token válido em uso
  When ele é revogado (ou o usuário é bloqueado, ou o perfil muda)
  Then a chamada seguinte ao /mcp é recusada / a análise deixa de ser permitida — sem janela de cache

Scenario: Concorrência
  Given 10 clientes simultâneos executando análises
  When o load_test roda por 60s
  Then não há erro de concorrência, o pool não se esgota e toda execução está em execution_history
```

## 6. Testes

### 6.1 Testes Unitários (mocks, como nas F9–F14)
```python
class TestPostgresPoolConfig:
    @pytest.mark.asyncio
    async def test_pool_usa_padrao_do_env(self): ...      # create_pool recebe min=10/max=10
    @pytest.mark.asyncio
    async def test_pool_respeita_connection_config(self): ...  # pool_min_size/pool_max_size
    @pytest.mark.asyncio
    async def test_pool_respeita_env(self): ...            # PG_POOL_* alterados

class TestSettingsPool:
    def test_max_menor_que_min_falha(self): ...
    def test_min_menor_que_1_falha(self): ...
```
Benchmark e load_test não têm teste unitário do tempo medido (instável); só do parsing de argumentos e do cálculo de percentis.

### 6.2 Checklist de Testes
- [ ] Baseline do benchmark registrada **antes** das mudanças (§10)
- [ ] Teste unitário: pool com padrão, via `.env` e via `connection_config`
- [ ] Teste unitário: validação de `PG_POOL_*` / `CONFIG_DB_POOL_*` no startup
- [ ] `EXPLAIN ANALYZE` das queries de permissão com volume realista, anexado à spec
- [ ] Suíte completa (480+) verde
- [ ] Manual: `benchmark.py --compare` com números antes/depois
- [ ] Manual: `load_test.py` com 10+ clientes e conferência de `execution_history`
- [ ] Manual: revogar token / bloquear usuário durante o teste e confirmar recusa imediata

## 7. Mudanças na Configuração
**Variáveis de Environment (.env):**
```
PG_POOL_MIN_SIZE=10           # pool de cada data source PostgreSQL (padrão = atual)
PG_POOL_MAX_SIZE=10
CONFIG_DB_POOL_MIN_SIZE=10    # pool do Config DB (ver §11 #1)
CONFIG_DB_POOL_MAX_SIZE=10
```
Acrescentar também aos três `docker-compose.*.yml` (`${VAR:-10}`) e ao `.env.example`. Sem as variáveis, nada muda.

## 8. Documentação
### 8.1 Como a feature aparece no MCP
Não aparece: nenhuma tool, parâmetro ou contrato de resposta muda.

### 8.2 Como o usuário usa essa feature
- Operador: ajusta `PG_POOL_*` / `CONFIG_DB_POOL_*` no `.env` conforme o nº de clientes simultâneos e o limite de conexões do PostgreSQL (`max_connections`).
- Desenvolvedor: roda `python scripts/benchmark.py` antes e depois de uma mudança de performance e compara com `--compare`.

### 8.3 Como outros desenvolvedores estenderão isso
Novas metas de performance entram como mais um caso em `scripts/benchmark.py`. Pool para outros bancos seguiria o mesmo padrão (`connection_config` sobrepõe o `.env`) — fora desta feature.

## 9. Checklist de Implementação
**Código:**
- [ ] Baseline do benchmark (antes de mexer em qualquer coisa)
- [ ] `config.py` + `adapters/postgresql.py` + `database/connection.py` (pool)
- [ ] `.env.example` e compose atualizados
- [ ] `EXPLAIN ANALYZE` e índices **só se** justificados
- [ ] `scripts/benchmark.py` e `scripts/load_test.py`
- [ ] Testes passing (100% dos casos), docstrings
- [ ] Medições da §4.5 registradas (com decisão "alterar / não alterar")

**Documentação:**
- [ ] FEATURES_ROADMAP.md (tabela, timeline, rodapé), CLAUDE.md, DATABASE_SCHEMA.md/ARQUITETURA.md se houver índice, notas nas specs F11 (#7) e F14 (#4)

**QA:**
- [ ] Code review aprovado
- [ ] PR merge aprovado

## 10. Decisões desta sessão (2026-10-05)
| # | Decisão |
|---|---|
| 1 | **Entra:** pool PostgreSQL configurável pelo `.env`, padrão = comportamento atual (10). Só PostgreSQL. |
| 2 | **Entra:** benchmark reproduzível das metas de RNF1, com baseline antes/depois, fora da suíte padrão. |
| 3 | **Auth/permissões: só medir e indexar.** Sem cache de token/permissão — preserva bloqueio e revogação imediatos da F12 (ADR-007). |
| 4 | **Cache (F7): só medir.** Código só muda se o benchmark mostrar problema. |
| 5 | **Teste de carga: script manual**, fora dos 480 testes. |
| 6 | **Fora:** log assíncrono do `execution_history` (arrisca RNF4 — 100% registrado). |
| 7 | **Fora:** `sslmode` (F11 #1) e `translate_params` (F11 #5) — features próprias, sem relação com performance. |
| 8 | **Fora:** análises assíncronas com status check (RNF1 "pesadas > 5s") — muda o contrato da F5 e a arquitetura; feature própria. |

**Baseline do benchmark (2026-10-07, pool 10/10 = comportamento anterior):** 50 iterações, `benchmark.py` rodado DENTRO do container do app (o data source aponta para o host `postgres`), compose local, 1 data source, 2 análises, 6 linhas em `vendas` (volume mínimo; latência de rede ~1 ms — §11 #4).

| medição | p50 ms | p95 ms | meta |
|---|---|---|---|
| cache_hit | 13,98 | 17,45 | < 100 ✅ |
| count (COUNT(*)) | 0,90 | 3,84 | < 500 ✅ |
| list_tools (c/ auth) | 12,10 | 14,55 | < 2000 ✅ |
| light_analysis (miss) | 19,34 | 22,24 | < 5000 ✅ |
| auth (referência) | 9,99 | 11,38 | — |

Um cache hit custa ~14 ms, quase todo em idas ao Config DB (auth ≈ 10 ms dos 14).

## 11. Pontos em aberto (a confirmar antes de implementar)
| # | Ponto | Proposta |
|---|---|---|
| 1 | O `PostgreSQLAdapter` é o mesmo para o Config DB e para os data sources. Um único par `PG_POOL_*` ou pares separados? | **Pares separados** (`PG_POOL_*` e `CONFIG_DB_POOL_*`): o Config DB recebe ≥7 idas por chamada e tem perfil de carga diferente |
| 2 | `touch_last_used` faz UPDATE a cada chamada. Throttle (gravar só se passou N minutos) entra se o benchmark mostrar custo? | Só com evidência; não afeta revogação, mas muda a semântica de `last_used_at` (passa a ser aproximada) |
| 3 | Reaproveitar a `Analysis` carregada em `call_tool` dentro de `execute()` evita 1 SELECT, mas muda a assinatura de `execute()` (usada por testes e por futuro Celery) | Só com evidência de ganho relevante |
| 4 | Ambiente de medição: o benchmark roda contra o Postgres do compose local (`localhost:5433`) — latência ~1ms (ARQUITETURA.md §1095). Números em rede real (remoto) serão maiores | Registrar o ambiente junto da baseline |

## 12. Implementação (2026-10-07)
**Feito:** `PG_POOL_*` e `CONFIG_DB_POOL_*` (`config.py`, validação no startup, padrão 10/10); `PostgreSQLAdapter.connect()` passa `min_size`/`max_size` (chaves `pool_min_size`/`pool_max_size` do `connection_config` sobrepõem o `.env`); `database/connection.py` usa o par `CONFIG_DB_POOL_*` (§11 #1); `.env.example` e os 3 compose; `scripts/benchmark.py`, `scripts/load_test.py`, `scripts/perf_stats.py`; testes (500/500 ✅, `.venv` do projeto). `benchmark-*.json` no `.gitignore`.

**Medições (2026-10-07, ambiente: compose local, Windows/Docker Desktop):**
- **Baseline:** §10. Todas as metas de RNF1 com folga de 1–2 ordens de grandeza.
- **EXPLAIN (ANALYZE, BUFFERS):** a query de permissão faz `Seq Scan` só em `profiles`/`analyses` (1–2 linhas, 0,148 ms no total); `get_by_name` usa `analyses_name_key`. Volume testado é mínimo (2 análises, 1 perfil) — **não há evidência para índice**, nenhum foi criado. Reavaliar com 100+ análises e muitos perfis (RNF3) antes de fechar a decisão.
- **Carga (`load_test.py`, 10 clientes, 60 s, 2 análises hit+miss, token admin):** 3114 execuções, 0 erros, p50 189 ms / p95 264 ms, ~52 req/s; `execution_history` gravou 3114/3114 (RNF4 ✅). Com `CONFIG_DB_POOL_*=30` (30 s): 1524 execuções, ~51 req/s, p50 188 ms — **o pool do Config DB não é o gargalo** nessa carga (o cliente Python e o servidor, ambos num único processo/laptop, provavelmente são). A latência com 10 clientes (~190 ms) é ~13x a de 1 cliente (~14 ms).
- **Revogação/perfil (manual via curl):** com análise liberada → `success`; vínculo perfil↔análise removido → `ANALYSIS_NOT_FOUND` na chamada seguinte; vínculo restaurado → `success`; `POST /auth/revoke` → 401 na chamada seguinte. Imediato, sem janela de cache. **Bloqueio de usuário não foi testado** (bloquearia o admin).
- **§4.5:** `touch_last_used`, cache F7 e o 2º SELECT de `analyses` **não foram isolados** — a carga acima não mostrou gargalo atribuível a eles; decisão: **não alterar**.
- Achados dos scripts: o benchmark precisou rodar no container; `load_test.py` não podia imprimir `≈`/`≥` no console cp1252 (corrigido). A revogação foi testada à parte, não *durante* o load test.

**Pendente:**
- [ ] Bloqueio de usuário (`is_blocked`) com recusa imediata
- [ ] EXPLAIN com volume realista (100+ análises, muitos perfis)
- [ ] Repetir em rede real/remoto
- A análise temporária `bench_nocache` ficou **inativa** no banco local (tem histórico, não pôde ser apagada).
