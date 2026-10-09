# Contrato do endpoint `/mcp`

O `/mcp` é o endpoint do protocolo MCP (Streamable HTTP, JSON-RPC) e **não aparece** no Swagger/OpenAPI. As demais rotas (`/auth`, `/me`, `/admin/*`, `/health`) estão em [`openapi.json`](openapi.json) e, em ambiente local, no `/docs`.

Fontes: `ARQUITETURA.md` §3.4.1 (contrato de erro), `src/mcp_transport/tools.py`, `src/services/analysis_service.py`, `src/services/volume_guard_service.py`.

## 1. Conexão e autenticação

- Endpoint único `/mcp`, **Streamable HTTP stateless**: cada requisição é independente, sem `Mcp-Session-Id`. TLS é obrigatório fora do ambiente local (em local, HTTP puro é aceito).
- **Toda** chamada exige `Authorization: Bearer <token>`. Sem token, ou com token inválido, expirado ou revogado, ou de usuário bloqueado, a resposta é sempre o mesmo `401`:

```json
{ "error": "unauthorized", "message": "Token de acesso inválido ou ausente." }
```

- Para obter o token: `POST /auth/token` com `email` e `password` (veja o `openapi.json`; em local, o botão **Authorize** do `/docs`). Para revogar: `POST /auth/revoke`.

## 2. `list_tools`

Devolve uma tool por **análise ativa liberada ao usuário** (pelos perfis dele):

| Campo | Valor |
|---|---|
| `name` | `execute_<nome da análise>` |
| `description` | `description` da análise |
| `inputSchema` | JSON Schema gerado de `analyses.parameters`, mais a propriedade `confirmar_volume_alto` |

`confirmar_volume_alto` é booleana (padrão `false`): confirma a execução mesmo que o resultado seja grande (maior consumo de tokens). Análises com nome fora do padrão de identificador MCP são ignoradas (log de aviso). Falha do Config DB vira um erro MCP genérico (`-32603`), sem detalhes internos.

## 3. `call_tool`

Chame `execute_<nome>` com os parâmetros da análise (e, opcionalmente, `confirmar_volume_alto`). O retorno é sempre um objeto estruturado com `status`; o servidor **nunca propaga exceção**.

### 3.1 `status: "success"`

```json
{ "status": "success", "data": [ { "regiao": "Sul", "total": 1500.0 } ], "cached": false }
```

- `data`: dataset bruto (o servidor não transforma nem agrega; quem interpreta é o LLM do cliente).
- `cached`: `true` se veio do cache em memória.
- `aviso` (opcional): `"resultado grande, enviado por confirmação explícita"` — presente quando o resultado excedia o limite e foi enviado por `confirmar_volume_alto=true`.

### 3.2 `status: "volume_exceeded"`

O Controle de Volume (pré-checagem `COUNT(*)` e tamanho em KB) recusa resultados acima dos limites do servidor:

```json
{
  "status": "volume_exceeded",
  "estimativa": { "linhas": 12000, "tamanho_estimado_kb": 900.5 },
  "limite": { "linhas": 500, "tamanho_kb": 150 },
  "mensagem": "Sua consulta retornaria aproximadamente 12000 linhas (...). Refine o período ou adicione filtros ...",
  "cached": false
}
```

Os limites vêm de `DEFAULT_MAX_RESULT_ROWS` e `DEFAULT_MAX_RESULT_SIZE_KB`. Duas saídas: **refinar** (período, filtros) e chamar de novo, ou repetir a chamada com `confirmar_volume_alto=true`.

### 3.3 `status: "error"`

```json
{
  "status": "error",
  "error_code": "QUERY_TIMEOUT",
  "retryable": true,
  "mensagem": "A consulta excedeu o tempo limite de 30s. Refine o período ou adicione filtros.",
  "cached": false
}
```

| `error_code` | Quando | `retryable` |
|---|---|---|
| `ANALYSIS_NOT_FOUND` | Análise inexistente, inativa **ou sem permissão** (indistinguíveis: quem não tem acesso não descobre que ela existe) | false |
| `INVALID_PARAMETERS` | Parâmetros não batem com a definição da análise; `confirmar_volume_alto` não booleano; `arguments` não é objeto | false |
| `INVALID_ANALYSIS_CONFIG` | Erro de cadastro da análise (schema de parâmetros, step ausente, SQL que não é SELECT, `cache_frequency` inválido) | false |
| `DATA_SOURCE_UNAVAILABLE` | Data source inativo ou conexão indisponível (após as tentativas) | true |
| `QUERY_TIMEOUT` | A query excedeu `QUERY_TIMEOUT_SECONDS` | true (com filtro mais estreito) |
| `QUERY_FAILED` | O banco rejeitou ou falhou o SQL | false |
| `INTERNAL_ERROR` | Qualquer outra falha (inclui o Config DB indisponível) | false |

`retryable` indica se repetir **a mesma chamada** pode dar certo mais tarde; em `QUERY_TIMEOUT`, repita com um filtro mais estreito.

## 4. Regras do servidor

- **Acesso negado = `ANALYSIS_NOT_FOUND`.** A permissão é revalidada a cada `call_tool`, antes de qualquer cache ou execução; um perfil alterado vale na chamada seguinte.
- **Retry automático** (`QUERY_RETRY_MAX_ATTEMPTS`, padrão 3, com backoff exponencial a partir de `QUERY_RETRY_BACKOFF_BASE_MS`) **só para falha rápida de conexão** ao data source. Nunca para timeout, erro de SQL ou validação.
- **Sem exceção vazada:** detalhes (host, SQL, stack) ficam no log do servidor, nunca na resposta.
- Cada execução é gravada em `execution_history` (inclusive o `user_id`), consultável por `GET /admin/executions`.

## 5. Configurar um cliente MCP

**Claude Code:**

```bash
TOKEN=$(cat secrets/admin-token.txt)   # ou o token emitido por POST /auth/token
claude mcp add --transport http --scope user analise-dados http://localhost:3000/mcp \
  --header "Authorization: Bearer $TOKEN"
```

Passo a passo completo, com HTTPS e solução de problemas: `README.md` §6. A configuração de outros clientes MCP (Claude Desktop, Gemini, OpenAI) fica para a F21 (User Documentation).
