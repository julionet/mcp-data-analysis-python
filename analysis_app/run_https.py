"""Sobe o servidor em HTTPS com ALPN habilitado (validado no protótipo F0).

A CLI padrão do uvicorn (--ssl-keyfile/--ssl-certfile) não negocia ALPN
(confirmado com `openssl s_client -alpn h2,http/1.1`: "No ALPN negotiated").
Clientes com stack TLS mais estrita (ex.: Electron/Chromium do Claude Desktop)
podem abortar a conexão sem nunca chegar a enviar uma requisição HTTP nesse
caso. Por isso o uvicorn é subido programaticamente com ssl_context_factory.
"""

import uvicorn
from uvicorn.config import Config

from config import settings


def alpn_ssl_context_factory(config: Config, default_factory):
    context = default_factory()
    context.set_alpn_protocols(["http/1.1"])
    return context


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.server_host,
        port=settings.server_port,
        ssl_keyfile=settings.tls_key_file,
        ssl_certfile=settings.tls_cert_file,
        ssl_context_factory=alpn_ssl_context_factory,
    )
