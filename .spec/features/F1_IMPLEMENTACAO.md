# F1 — Implementação: FastAPI + MCP Server Setup via Streamable HTTP com TLS

**Spec de origem:** [F1_FastAPI_MCP_Server_Setup.md](./F1_FastAPI_MCP_Server_Setup.md)
**Referências:** ARQUITETURA.md (ADR-006, §5.1, §5.2, §6.1) · NEGOCIO.md (RNF2, RNF5, T4)
**Status:** 🟩 Done — implementado, testado (unitário + aceitação) e validado manualmente com Claude Desktop (confirmado por Jose, 2026-09-23)

## 1. O que foi entregue

A camada de transporte do servidor MCP: um processo FastAPI/uvicorn que serve o protocolo MCP via Streamable HTTP, com TLS obrigatório e ALPN negociado explicitamente, na porta 3000. Nenhuma análise real está cadastrada ainda (`list_tools()` retorna `[]`, `call_tool()` levanta `NotImplementedError`) — isso é escopo de F5.

## 2. Arquivos criados/alterados

```
analysis_app/
├─ main.py                    — FastAPI app entry point; monta o transporte MCP e expõe /health
├─ config.py                  — Settings via pydantic-settings (.env): host, porta, caminhos TLS
├─ run_https.py                — launcher uvicorn com ssl_context_factory (ALPN)
├─ requirements.txt            — já existente, conforme spec §7 (sem alteração)
├─ requirements-dev.txt        — novo: pytest + httpx, apenas para rodar a suíte de testes
├─ .env                        — novo (gitignored): valores locais, aponta para certs/localhost+1*.pem
├─ certs/                      — já existentes (mkcert): localhost+1.pem / localhost+1-key.pem
├─ mcp_transport/               — renomeado a partir de mcp/ (ver §3 — decisão de nomenclatura)
│  └─ __init__.py              — Server de baixo nível + StreamableHTTPSessionManager, stubs de list_tools/call_tool
└─ tests/
   └─ test_server_setup.py     — novo: 3 testes unitários (TestServerSetup, conforme spec §6.1)

.gitignore                     — adicionado `.env`
```

## 3. Decisão de arquitetura tomada durante a implementação (não coberta pela spec)

A spec (F1 §4.1/§4.4) nomeia a pasta do transporte MCP como `analysis_app/mcp/`. Ao implementar literalmente, esse pacote local colide de nome com o SDK `mcp` que ele mesmo importa (`from mcp.server.lowlevel import Server`): rodando a partir de `analysis_app/` (padrão usado no protótipo F0), o Python resolve `import mcp` para o pacote local antes do pacote instalado em `site-packages`, quebrando com `ModuleNotFoundError: No module named 'mcp.server'` — reproduzido durante a implementação.

**Decisão (confirmada com Jose):** renomear a pasta para `analysis_app/mcp_transport/`, mantendo o restante do wiring idêntico ao validado no protótipo F0 e a forma de subir o servidor (`cd analysis_app && python run_https.py`). Alternativa descartada: manter o nome `mcp/` e rodar o processo como pacote a partir da raiz do repositório (`analysis_app.main:app`) — rejeitada por exigir também ajustar os caminhos relativos de `certs/`/`.env`.

> Isso deve ser refletido em ARQUITETURA.md §5.2 (estrutura de pastas) quando o documento for revisado novamente — não alterado aqui, pois o pedido desta etapa foi só a implementação de F1.

## 4. Divergências pontuais em relação ao texto literal da spec

- **Certificados mkcert:** a spec usa `certs/localhost+2*.pem` como exemplo; os certificados já gerados no repo são `certs/localhost+1*.pem`. `run_https.py` não hardcoda o nome — lê de `config.py`/`.env` (`TLS_CERT_FILE`/`TLS_KEY_FILE`), então o nome real do arquivo é irrelevante para o código.
- **`.env` real vs. `.env.example`:** `.env.example` (committed) mantém os nomes genéricos do spec (`certs/server.pem`); `.env` (gitignored, novo) tem os valores reais de dev apontando para `localhost+1*.pem`. `.env` foi adicionado ao `.gitignore` (não estava lá antes).
- **`requirements-dev.txt`:** não mencionado na spec; adicionado porque o checklist §6 exige testes unitários rodáveis e `pytest`/`httpx` não estavam em `requirements.txt` (que é intencionalmente enxuto, só dependências de runtime).

## 5. Testes

### 5.1 Unitários (`pytest tests/test_server_setup.py`) — 3/3 passando

```
TestServerSetup::test_health_check_returns_ok                          PASSED
TestServerSetup::test_mcp_route_no_redirect_without_trailing_slash     PASSED
TestServerSetup::test_cors_middleware_configured                       PASSED
```

Detalhe de implementação do teste: `session_manager` (em `mcp_transport`) é um singleton de módulo cujo `.run()` só pode ser chamado uma vez por instância (levanta `RuntimeError` na segunda chamada). Por isso os 3 testes compartilham um único `TestClient` via fixture `scope="module"`, em vez de um `TestClient` novo por teste.

### 5.2 Critérios de aceitação (spec §5) — validados manualmente nesta sessão

| Cenário | Comando | Resultado |
|---|---|---|
| Handshake TLS/ALPN | `openssl s_client -alpn h2,http/1.1 -connect localhost:3000` | `ALPN protocol: http/1.1` ✅ |
| `/mcp` sem barra final não redireciona | `curl -X POST https://localhost:3000/mcp` | `406` (não `307`) ✅ |
| Health check | `curl https://localhost:3000/health` | `200 {"status":"ok"}` ✅ |
| HTTP puro não é servido | `curl http://localhost:3000/health` | conexão recusada (nenhum listener HTTP) ✅ |

### 5.3 Teste manual com cliente MCP real

- [x] Teste manual com Claude Desktop apontando para `https://<ip>:3000/mcp` — spec §6.2, executado e confirmado com sucesso por Jose (2026-09-23). Fecha o último critério de aceitação da spec que dependia de interação humana com o app desktop.

## 6. Questões da spec (§10) — o que ficou em aberto

Itens 1–6 já estavam resolvidos no texto da spec. O item 7 (TLS de produção via NGINX) permanece explicitamente **fora do escopo de F1** — a spec já registra que F1 usa TLS/ALPN diretamente no processo FastAPI (mkcert), e que a decisão de produção fica para quando o roadmap de produção (V1.2) for formalizado. Nenhuma mudança em ARQUITETURA.md foi feita a respeito, conforme a própria spec sugeria como opção.

## 7. Como rodar

```bash
cd analysis_app
python -m venv .venv && source .venv/bin/activate   # se ainda não existir
pip install -r requirements-dev.txt

# subir o servidor (TLS/ALPN):
python run_https.py
# → https://localhost:3000/mcp  |  https://localhost:3000/health

# rodar os testes unitários:
pytest tests/test_server_setup.py -v
```

## 8. Próximos passos

F1 está **concluída** (código, testes automatizados e teste manual com Claude Desktop) e pronta para servir de base para **F2 (PostgreSQL Adapter)**, conforme a ordem de dependências do FEATURES_ROADMAP.md. ARQUITETURA.md §5.2 já foi atualizado (v1.7 → v1.8) com o nome definitivo `mcp_transport/`. Fica como pendência apenas de processo, não de implementação: code review por pessoa e merge do PR (F1_FastAPI_MCP_Server_Setup.md §9). O item 7 das Questões Abertas da spec (TLS via NGINX em produção) segue intencionalmente fora do escopo de F1, a ser revisitado quando o roadmap de produção (V1.2) for formalizado.
