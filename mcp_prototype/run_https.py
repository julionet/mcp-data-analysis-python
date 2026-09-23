"""Sobe o protótipo em HTTPS com ALPN habilitado.

O CLI `uvicorn --ssl-keyfile/--ssl-certfile` não negocia ALPN (confirmado com
`openssl s_client -alpn h2,http/1.1`: "No ALPN negotiated"). Clientes com
stack TLS mais estrita (ex.: Electron/Chromium do Claude Desktop) podem
abortar a conexão sem nunca chegar a enviar uma requisição HTTP quando o
servidor não participa da negociação ALPN — resultando em "nenhum servidor
respondeu", mesmo com certificado válido e servidor no ar (confirmado via
curl e via cliente MCP oficial, que não fazem essa exigência).
"""

import uvicorn
from uvicorn.config import Config


def alpn_ssl_context_factory(config: Config, default_factory):
    context = default_factory()
    context.set_alpn_protocols(["http/1.1"])
    return context


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3000,
        ssl_keyfile="certs/localhost+2-key.pem",
        ssl_certfile="certs/localhost+2.pem",
        ssl_context_factory=alpn_ssl_context_factory,
    )
