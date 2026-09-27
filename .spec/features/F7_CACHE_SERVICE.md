# F7 Cache Service (In-Memory)

## Feature Spec

**ID:** F7
**Nome:** Cache Service (In-Memory)
**Prioridade:** 🟠 Alta
**Esforço Estimado:** 1d (8h)
**Status:** ⬜ Todo

---

## 1. Visão
Camada de cache em memória, integrada ao `AnalysisService.execute()`, que evita reexecutar a query no BD quando a mesma análise é pedida com os mesmos parâmetros dentro do TTL. Reduz latência e carga nos data sources, e preserva o Volume Guard (F3) mesmo em cache hit.

## 2. Objetivo
Servir resultados repetidos sem tocar o BD, com TTL por análise (`cache_frequency`), limites de memória e proteção contra requisições simultâneas idênticas, sem impedir a futura troca do backend por Redis.

**Métrica de Sucesso:**
- ✅ Cache hit responde em < 100ms (NEGOCIO.md RNF1)
- ✅ TTL respeita `cache_frequency` (`hourly`=1h, `daily`=24h corridas desde a gravação, `weekly`=7d, `none`=sem cache)
- ✅ Duas requisições simultâneas idênticas com cache vazio executam a query uma única vez
- ✅ Volume Guard nunca é contornado por cache (hit grande sem `confirmar_volume_alto` devolve `volume_exceeded`)
- ✅ Somente resultados `success` são cacheados
- ✅ Memória do cache limitada por `CACHE_MAX_ENTRIES` e `CACHE_MAX_SIZE_MB` (RNF3: footprint total < 500MB)
- ✅ Trocar para Redis no futuro não exige mudar `CacheService` nem `AnalysisService`

## 3. Contexto
**Depende de:** F4 (Analysis Execution Engine), F3 (Controle de Volume, cujos limites são reutilizados)
**É dependência de:** F8 (Log de Execução, grava a coluna `execution_history.cached`), F9/F10 (versionamento, ver nota em 4.2), F16 (Performance Optimization)

**Decisões já tomadas (conversa de definição do F7):**
- O cache fica **dentro de `AnalysisService.execute()`**, não em `mcp_transport/tools.py`. `execute()` já carrega a análise (id, `updated_at`, `cache_frequency`) e atende qualquer chamador (`call_tool` hoje, Celery no futuro). O diagrama de ARQUITETURA.md §3.2, que desenha o cache no `call_tool`, deve ser ajustado na próxima revisão do documento.
- `confirmar_volume_alto` **fica fora da chave** (híbrido: a entrada guarda `linhas` e `tamanho_kb`).
- `invalidate_by_source` **não** entra no F7.
- Interface `CacheBackend` com apenas `InMemoryBackend` agora; Redis fica para o ambiente remoto.

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
Componentes que serão criados/modificados:
├─ services/cache_backend.py          (novo)  → CacheBackend (ABC) + InMemoryBackend
├─ services/cache_service.py          (novo)  → CacheService (chave, TTL, lock, regras de volume no hit)
├─ services/analysis_service.py       (modif.) → integra CacheService em execute(); adiciona "cached" ao retorno
├─ config.py                          (modif.) → CACHE_BACKEND, CACHE_MAX_ENTRIES, CACHE_MAX_SIZE_MB
├─ main.py                            (modif.) → startup: instancia backend conforme CACHE_BACKEND (ARQUITETURA §6.1, passo 4)
└─ tests/test_cache_service.py        (novo)
```
Os nomes exatos de método e assinatura em `analysis_service.py` devem ser alinhados ao código real de F4/F5 já implementado.

### 4.2 Fluxo de Dados

**Posição do cache:**
```
Cliente MCP → mcp_transport/tools.py (traduz MCP → execute(), sem lógica de cache)
            → AnalysisService.execute(analysis_id, params, confirmar_volume_alto)
                 1. Carrega a análise (id, updated_at, cache_frequency)
                 2. Valida params (Pydantic)
                 3. Resolve TTL a partir de cache_frequency
                      └─ valor inválido → {"status":"error"} (nenhuma query executada)
                 4. cache_frequency = none → pula o cache (vai direto ao executor)
                 5. CacheService.get_or_execute(chave, ttl, confirmar_volume_alto, executor)
                 6. (F8, futuro) registra a execução
```

**Chave do cache:**
```
analysis:<analysis_id>:<sha256( updated_at | params_normalizados )>
```
- Params normalizados: JSON com chaves ordenadas (`sort_keys=True`, separadores compactos), defaults resolvidos e `None` tratado de forma consistente. `{a:1,b:2}` e `{b:2,a:1}` geram a mesma chave.
- `confirmar_volume_alto` não entra na chave.
- `analyses.updated_at` funciona como marcador de versão da análise: editar a análise muda a chave e a entrada antiga fica órfã até expirar ou ser despejada por LRU.
- O prefixo legível `analysis:<id>:` facilita a invalidação por padrão quando ela for implementada.

**Fluxo de `get_or_execute`:**
```
backend.get(chave)
 ├─ HIT (dentro do TTL)
 │    entrada excede o limite de volume atual (.env)?
 │     ├─ NÃO → devolve resultado, "cached": true (BD não é tocado)
 │     └─ SIM → confirmar_volume_alto = true?
 │               ├─ SIM → devolve resultado, "cached": true + "aviso"
 │               └─ NÃO → devolve volume_exceeded montado com linhas/KB da entrada,
 │                        "cached": false (BD não é tocado)
 └─ MISS (ou expirado)
      adquire lock da chave           ← requisições idênticas simultâneas esperam aqui
      backend.get(chave) novamente    ← double-check
       ├─ HIT → segue o fluxo de HIT
       └─ MISS → executor() (Volume Guard + query + checagem de KB, como no F4)
            ├─ status "success" → backend.set(chave, entrada, ttl); devolve "cached": false
            └─ "volume_exceeded" ou "error" → NÃO grava; devolve como veio, "cached": false
      libera o lock (sempre, inclusive em exceção)
```

**Estrutura da entrada guardada:**
```json
{
  "resultado": { "status": "success", "data": [ ... ] },
  "linhas": 8400,
  "tamanho_kb": 510,
  "gravado_em": "2026-09-26T21:40:00-03:00"
}
```
`linhas` e `tamanho_kb` permitem responder `volume_exceeded` sem consultar o BD.

**InMemoryBackend:**
```
get(chave)
 ├─ não existe → None
 ├─ existe e expirou (agora > expira_em) → remove, devolve None (expiração lazy)
 └─ existe e válido → marca como mais recente (LRU), devolve

set(chave, valor, ttl)
 ├─ tamanho do valor (JSON serializado) > CACHE_MAX_SIZE_MB → não grava, loga
 ├─ remove todas as entradas vencidas
 ├─ grava com expira_em = agora + ttl
 └─ enquanto (nº de entradas > CACHE_MAX_ENTRIES) ou (soma de MB > CACHE_MAX_SIZE_MB):
       despeja a menos usada recentemente (LRU)
```

**Mapa de TTL:**

| `cache_frequency` | Comportamento |
|---|---|
| `hourly` | TTL 3600s |
| `daily` | TTL 86400s (24h corridas desde a gravação) |
| `weekly` | TTL 604800s |
| `none` | Cache desligado para a análise (sem leitura, gravação ou lock) |
| outro valor | `status: "error"` com mensagem clara, log, nenhuma query executada |

**Notas para outras features:**
- **F9 (Version Management):** cada nova versão ou rollback deve atualizar `analyses.updated_at` (ou o marcador da chave deve passar a `version_number`), senão o cache serviria dado da versão anterior até o TTL expirar.
- **Limite conhecido:** editar `analysis_steps` diretamente por SQL sem tocar em `analyses.updated_at` só é refletido quando o TTL expira.
- **Lock distribuído:** o lock por chave é `asyncio.Lock` local ao processo. Com várias réplicas no ambiente remoto, precisará de lock distribuído (fora do F7).

### 4.3 Banco de Dados
Nenhuma mudança de schema. O cache vive em memória. A coluna `execution_history.cached` já existe (ARQUITETURA §2.2) e será preenchida pelo F8 a partir do campo `cached` retornado por `execute()`.

`analyses.cache_frequency` (`VARCHAR(50)`, default `'daily'`) já existe; o F7 passa a aceitar `daily`, `hourly`, `weekly` e `none`. Nenhum `CHECK` novo é adicionado; a validação é feita em código.

### 4.4 Endpoints/Interfaces
```python
# services/cache_backend.py
class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> dict | None: ...
    @abstractmethod
    async def set(self, key: str, value: dict, ttl_seconds: int) -> None: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...

class InMemoryBackend(CacheBackend):
    def __init__(self, max_entries: int, max_size_mb: int): ...
    # LRU (OrderedDict), TTL lazy, limpeza de vencidos a cada set()

# services/cache_service.py
class CacheService:
    def __init__(self, backend: CacheBackend, max_rows: int, max_size_kb: int): ...

    def build_key(self, analysis_id: UUID, updated_at: datetime, params: dict) -> str:
        """analysis:<id>:<sha256(updated_at|params normalizados)>"""

    @staticmethod
    def resolve_ttl(cache_frequency: str) -> int | None:
        """Retorna segundos, None para 'none'. Levanta InvalidCacheFrequencyError para valor desconhecido."""

    async def get_or_execute(
        self,
        key: str,
        ttl_seconds: int,
        confirmar_volume_alto: bool,
        executor: Callable[[], Awaitable[dict]],
    ) -> dict:
        """Fluxo hit/miss/lock/double-check descrito em 4.2. Retorna dict com 'cached'."""
```

**Contrato de retorno de `AnalysisService.execute()` com F7:**

| Situação | `status` | `cached` | Extras |
|---|---|---|---|
| Miss, executou | `success` | `false` | |
| Hit | `success` | `true` | |
| Hit grande com `confirmar_volume_alto=true` | `success` | `true` | `aviso` |
| Hit grande sem `confirmar_volume_alto` | `volume_exceeded` | `false` | `estimativa` e `limite` |
| Miss com volume alto | `volume_exceeded` | `false` | |
| Erro (query ou `cache_frequency` inválido) | `error` | `false` | `mensagem` |

O campo `cached` é acrescentado ao payload que o cliente MCP recebe.

## 5. Critérios de Aceitação
```gherkin
Feature: Cache Service (In-Memory)

Scenario: Segunda chamada idêntica é servida do cache
  Given uma análise com cache_frequency "daily" e cache vazio
  When o cliente A executa a análise com os params P
  And o cliente B executa a análise com os mesmos params P
  Then A recebe "cached": false e B recebe "cached": true
  And o BD de origem foi consultado apenas uma vez
  And B respondeu em menos de 100ms

Scenario: Params iguais em ordem diferente compartilham a chave
  Given uma execução com params {"a":1,"b":2} já cacheada
  When a análise é executada com {"b":2,"a":1}
  Then o resultado vem do cache

Scenario: Entrada expira pelo TTL
  Given uma análise com cache_frequency "hourly" cacheada há mais de 1h
  When a análise é executada de novo
  Then ocorre miss, a query é reexecutada e a entrada é regravada

Scenario: Requisições simultâneas idênticas com cache vazio
  Given cache vazio para a chave K
  When duas requisições idênticas chegam ao mesmo tempo
  Then a query é executada uma única vez
  And ambas recebem o mesmo resultado

Scenario: Hit grande sem confirmação preserva o Volume Guard
  Given um resultado de 8400 linhas cacheado via confirmar_volume_alto=true
  When a mesma análise é chamada sem confirmar_volume_alto
  Then a resposta é volume_exceeded com linhas/KB guardados
  And o BD não é consultado

Scenario: Hit grande com confirmação
  Given o mesmo resultado grande cacheado
  When a análise é chamada com confirmar_volume_alto=true
  Then o resultado é devolvido com "cached": true e "aviso"

Scenario: cache_frequency none
  Given uma análise com cache_frequency "none"
  When ela é executada duas vezes
  Then ambas consultam o BD e retornam "cached": false

Scenario: Resultados não bem-sucedidos não são cacheados
  Given uma execução que retornou volume_exceeded ou error
  When a mesma análise é executada de novo
  Then ocorre miss e o executor roda novamente

Scenario: cache_frequency inválido
  Given uma análise com cache_frequency "mensal"
  When a análise é executada
  Then o retorno é status "error" com mensagem listando os valores aceitos
  And nenhuma query é executada

Scenario: Análise editada invalida a entrada antiga
  Given uma entrada cacheada para a análise
  When analyses.updated_at muda
  Then a próxima execução dá miss

Scenario: Limites de memória
  Given CACHE_MAX_ENTRIES=2
  When 3 chaves distintas são gravadas
  Then a menos usada recentemente é despejada
  And um resultado maior que CACHE_MAX_SIZE_MB sozinho não é gravado (com log)

Scenario: CACHE_BACKEND inválido
  Given CACHE_BACKEND=xyz
  When o servidor inicia
  Then o startup falha com erro claro
```

## 6. Testes

### 6.1 Testes Unitários
```python
class TestInMemoryBackend:
    @pytest.mark.asyncio
    async def test_set_get_roundtrip(self): ...
    @pytest.mark.asyncio
    async def test_ttl_expiration_lazy(self): ...
    @pytest.mark.asyncio
    async def test_lru_eviction_by_entries(self): ...
    @pytest.mark.asyncio
    async def test_lru_eviction_by_size(self): ...
    @pytest.mark.asyncio
    async def test_oversized_value_not_stored(self): ...

class TestCacheService:
    def test_build_key_order_independent(self): ...
    def test_build_key_changes_with_updated_at(self): ...
    def test_resolve_ttl_values(self): ...
    def test_resolve_ttl_invalid_raises(self): ...
    @pytest.mark.asyncio
    async def test_miss_then_hit(self): ...
    @pytest.mark.asyncio
    async def test_success_only_is_cached(self): ...
    @pytest.mark.asyncio
    async def test_concurrent_identical_requests_single_execution(self): ...
    @pytest.mark.asyncio
    async def test_lock_released_on_executor_exception(self): ...
    @pytest.mark.asyncio
    async def test_large_hit_without_confirmation_returns_volume_exceeded(self): ...
    @pytest.mark.asyncio
    async def test_large_hit_with_confirmation_returns_aviso(self): ...

class TestAnalysisServiceCache:
    @pytest.mark.asyncio
    async def test_cache_frequency_none_bypasses_cache(self): ...
    @pytest.mark.asyncio
    async def test_invalid_cache_frequency_returns_error_without_query(self): ...
    @pytest.mark.asyncio
    async def test_cached_flag_in_payload(self): ...
```

### 6.2 Checklist de Testes
- [ ] Teste unitário: caso de sucesso (miss → hit)
- [ ] Teste unitário: validação de entrada (`cache_frequency` inválido, `CACHE_BACKEND` inválido)
- [ ] Teste unitário: tratamento de erro (`error` e `volume_exceeded` não cacheados; lock liberado em exceção)
- [ ] Teste unitário: concorrência (lock por chave + double-check)
- [ ] Teste unitário: limites (LRU por entradas e por MB, TTL)
- [ ] Teste de integração: `call_tool` → `execute()` → cache com PostgreSQL real
- [ ] Manual: 2 chamadas seguidas em pelo menos 1 cliente MCP real, com a segunda em < 100ms e `"cached": true`

## 7. Mudanças na Configuração
**Variáveis de Environment (.env):**
```
CACHE_BACKEND=memory        # único valor válido no F7; outro valor falha no startup
CACHE_MAX_ENTRIES=200       # pior caso normal ~30MB (200 x 150KB, limite padrão do Volume Guard)
CACHE_MAX_SIZE_MB=100       # ~20% do orçamento de 500MB (RNF3); cobre resultados de confirmar_volume_alto=true
```
`CACHE_MAX_ENTRIES` e `CACHE_MAX_SIZE_MB` valem apenas para o `InMemoryBackend`. No Redis (futuro), o limite fica com o `maxmemory-policy` do próprio Redis.

Reutiliza `DEFAULT_MAX_RESULT_ROWS` e `DEFAULT_MAX_RESULT_SIZE_KB` (F3) para decidir o comportamento em hit grande.

## 8. Documentação
### 8.1 Como a feature aparece no MCP
Não há tool nova. O payload retornado por `call_tool` ganha o campo `"cached": true|false`. O comportamento de `confirmar_volume_alto` continua o mesmo do ponto de vista do cliente.

### 8.2 Como o usuário usa essa feature
Transparente: repetir a mesma análise com os mesmos parâmetros retorna mais rápido. O TTL é definido por análise na coluna `analyses.cache_frequency` (`hourly`, `daily`, `weekly`, `none`), via SQL, como o resto da configuração.

### 8.3 Como outros desenvolvedores estenderão isso
- Novo backend (Redis): implementar `CacheBackend` (`get`/`set`/`delete`, valores JSON-serializáveis, `SETEX` para TTL) e registrá-lo no startup sob um novo valor de `CACHE_BACKEND`. Requer lock distribuído para o cenário com réplicas.
- Invalidação por fonte (`invalidate_by_source`): fora do F7; a chave com prefixo `analysis:<id>:` foi pensada para isso.

## 9. Checklist de Implementação
**Código:**
- [ ] `CacheBackend` e `InMemoryBackend` implementados
- [ ] `CacheService` (chave, TTL, lock por chave com double-check, regras de volume no hit)
- [ ] Integração em `AnalysisService.execute()` com campo `cached`
- [ ] `config.py`, `.env.example` e startup (`CACHE_BACKEND`)
- [ ] Code review completo
- [ ] Testes passing (100% dos casos)
- [ ] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] PR merge aprovado

**Documentação a atualizar após o merge:**
- [ ] FEATURES_ROADMAP.md: status do F7
- [ ] ARQUITETURA.md: diagrama §3.2 (cache dentro do `AnalysisService`) e §2.1

---

## Premissas assumidas (a confirmar na revisão da spec)
1. **`cached` em `volume_exceeded` vindo do cache:** `false`, pois nenhum resultado foi entregue.
2. **Limites de volume no hit:** comparados aos limites **atuais** do `.env`. Se o limite for reduzido, entradas antigas maiores passam a devolver `volume_exceeded`.
3. **Marcador de versão:** `analyses.updated_at`, com o limite conhecido descrito em 4.2.
