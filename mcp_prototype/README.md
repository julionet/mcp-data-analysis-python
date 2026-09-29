# Protótipo F0 — MCP em Memória

Protótipo mínimo que valida o núcleo da arquitetura (ADR-006, ver `../.spec/v1.0/ARQUITETURA.md`): um servidor MCP via **Streamable HTTP**, com `list_tools`/`call_tool`, dados e log de execução em memória — sem PostgreSQL, sem Handler Registry dinâmico, sem versionamento. Detalhes completos da spec em `../.spec/v1.0/F0_PROTOTIPO_MCP_MEMORIA.md`.

## Arquivos

- `main.py` — servidor MCP (`mcp.server.lowlevel.Server`) montado sobre FastAPI via `StreamableHTTPSessionManager`, endpoint único em `/mcp` (mais rota exata sem trailing slash, CORS habilitado), mais um `/health` para inspeção manual
- `fake_data.py` — análise fake (`vendas_por_regiao`), linhas fake e `EXECUTION_LOG`
- `fake_handler.py` — handler fake de transformação (ordena por vendas e marca a maior região)
- `run_https.py` — launcher para subir em HTTPS com ALPN habilitado (necessário para clientes como Claude Desktop; ver seção abaixo)
- `requirements.txt` — dependências

## Requisitos

- Python 3.11+ (o sistema pode ter uma versão mais antiga como padrão — confirme com `python3 --version`; se necessário, instale 3.11+ via `brew install python@3.12` ou similar)

> ⚠️ `mcp` está fixado em `1.30.0`, e não `>=1.2.0` como no documento de spec original: a partir da `2.0.0` o SDK removeu os decorators `@server.list_tools()`/`@server.call_tool()` usados aqui. `1.30.0` é a última versão 1.x com essa API, confirmada compatível com o código deste protótipo.

## Instalação

```bash
cd mcp_prototype
python3.12 -m venv .venv   # ou outro Python 3.11+ disponível
source .venv/bin/activate
pip install -r requirements.txt
```

## Executar o servidor (HTTP)

```bash
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 3000
```

Endpoint MCP único: `http://<ip-da-maquina>:3000/mcp`
Smoke test manual (sem cliente MCP): `http://<ip-da-maquina>:3000/health`

## Executar o servidor com HTTPS (necessário para Claude Desktop)

Claude Desktop exige `https://` para conectores remotos. Para desenvolvimento local, use [mkcert](https://github.com/FiloSottile/mkcert) para gerar um certificado confiável apenas nesta máquina (sem tocar em nada além do seu próprio Keychain):

```bash
brew install mkcert
mkcert -install          # instala a CA local no Keychain do macOS (pede senha uma vez)

cd mcp_prototype
mkdir -p certs && cd certs
mkcert localhost 127.0.0.1 ::1
cd ..
```

Isso gera `certs/localhost+2.pem` e `certs/localhost+2-key.pem` (ignorados pelo `.gitignore` — nunca commitar chave privada). Depois suba o servidor com o launcher `run_https.py` (não use `uvicorn ... --ssl-keyfile=...` direto pela CLI — ver aviso abaixo):

```bash
source .venv/bin/activate
python3 run_https.py
```

Endpoint MCP único: `https://127.0.0.1:3000/mcp`
Smoke test manual: `curl https://127.0.0.1:3000/health` (deve responder sem aviso de certificado)

> ⚠️ Use `run_https.py`, não `uvicorn --ssl-keyfile=... --ssl-certfile=...` direto pela CLI: a CLI não negocia ALPN e o Claude Desktop abandona a conexão TLS. Racional, diagnóstico e escopo (cliente em outra máquina): `../.spec/ARQUITETURA.md` §14.1.

## Por que existe `_MCPExactPathASGI` em `main.py`

Rota exata `/mcp` para evitar o `307` do `Mount` do Starlette quando o cliente usa a URL sem barra final. Racional completo e evidências: `../.spec/ARQUITETURA.md` §14.1 (item 2).

## Testar com Claude Desktop / ChatGPT Desktop

Configure cada cliente apontando para a mesma URL, sem header nem API Key (sem autenticação em V1.0):

```json
{
  "mcpServers": {
    "analysis": { "url": "https://127.0.0.1:3000/mcp" }
  }
}
```

Depois, em cada cliente:
1. Peça para listar as ferramentas disponíveis → deve aparecer `vendas_por_regiao`
2. Peça para executar `vendas_por_regiao` com `{"mes": "2026-09"}` → o resultado deve vir ordenado por vendas desc, com `"destaque": true` no primeiro item
3. Tente uma análise inexistente → deve retornar um erro claro, não uma stack trace

Checklist completo em `../.spec/v1.0/F0_PROTOTIPO_MCP_MEMORIA.md` (seção 6).

## Testar com Claude Code

Com o servidor no ar via `python3 run_https.py`, registre-o no Claude Code:

```bash
claude mcp add --transport http notas-prototipo https://127.0.0.1:3000/mcp
```

`http` é o transporte genérico para conexões remotas no Claude Code (cobre HTTP e HTTPS, streamable HTTP incluso) — não existe um valor `streamable-http` separado.

Escopo (opcional, padrão `local` — só este projeto, não versionado):
```bash
claude mcp add --transport http notas-prototipo --scope project https://127.0.0.1:3000/mcp  # via .mcp.json versionado
claude mcp add --transport http notas-prototipo --scope user https://127.0.0.1:3000/mcp     # todos os projetos
```

Verificar, listar, remover:
```bash
claude mcp list                    # lista com status de conexão
claude mcp get notas-prototipo     # detalhes desse servidor
/mcp                               # dentro de uma sessão do Claude Code, status interativo
claude mcp remove notas-prototipo
```

Depois, dentro de uma sessão do Claude Code, peça para listar as ferramentas disponíveis (`vendas_por_regiao` deve aparecer) e para executá-la — mesmos critérios de aceitação da seção anterior. **Testado com sucesso.**

> Se `claude mcp add`/`claude mcp list` reclamar de certificado (Claude Code é uma CLI Node.js, que não necessariamente confia no Keychain do macOS da mesma forma que o `curl`), aponte para a CA do mkcert antes de rodar o comando, em vez de desabilitar validação TLS por completo:
> ```bash
> export NODE_EXTRA_CA_CERTS="$(mkcert -CAROOT)/rootCA.pem"
> claude mcp add --transport http notas-prototipo https://127.0.0.1:3000/mcp
> ```

## Testar sem os clientes desktop (simulação via SDK)

Sem Claude Desktop/ChatGPT Desktop à mão, é possível simular dois clientes MCP com o próprio SDK `mcp` (`mcp.client.streamable_http`), abrindo duas sessões independentes contra o mesmo endpoint `/mcp` e chamando `list_tools()`/`call_tool()` em cada uma — é assim que este protótipo foi validado durante o desenvolvimento.

> Ao testar contra `https://127.0.0.1:3000/mcp` com um script Python (httpx/certifi, não o Keychain do macOS), é preciso apontar explicitamente para a CA do mkcert: `SSL_CERT_FILE="$(mkcert -CAROOT)/rootCA.pem" python3 seu_script.py`. `curl` não precisa disso (usa o Keychain do sistema).

## Fora do escopo deste protótipo

Persistência, Handler Registry dinâmico, cache, versionamento, múltiplos adapters de BD e teste de concorrência real — ver seção 8 da spec.
