"""run_https.py — F17 (decisão 9): ponto de entrada testado com uvicorn.run simulado + runpy."""

import runpy
import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import run_https
from config import settings

SCRIPT = str(Path(run_https.__file__))


def _run_as_main(**overrides):
    with (
        patch("uvicorn.run") as run,
        patch.multiple(settings, **overrides),
    ):
        runpy.run_path(SCRIPT, run_name="__main__")
    return run


class TestRunHttps:
    def test_tls_enabled_serves_https_with_cert_key_and_alpn_factory(self):
        run = _run_as_main(tls_enabled=True, tls_key_file="k.pem", tls_cert_file="c.pem",
                           server_host="0.0.0.0", server_port=3000)

        run.assert_called_once()
        args, kwargs = run.call_args
        assert args == ("main:app",)
        assert (kwargs["host"], kwargs["port"]) == ("0.0.0.0", 3000)
        assert (kwargs["ssl_keyfile"], kwargs["ssl_certfile"]) == ("k.pem", "c.pem")
        assert kwargs["ssl_context_factory"].__name__ == "alpn_ssl_context_factory"

    def test_tls_disabled_serves_plain_http_without_ssl_arguments(self):
        run = _run_as_main(tls_enabled=False, server_host="127.0.0.1", server_port=3000)

        args, kwargs = run.call_args
        assert args == ("main:app",)
        assert kwargs == {"host": "127.0.0.1", "port": 3000}

    def test_alpn_factory_restricts_protocols_to_http11(self):
        context = MagicMock(spec=ssl.SSLContext)

        result = run_https.alpn_ssl_context_factory(MagicMock(), lambda: context)

        assert result is context
        context.set_alpn_protocols.assert_called_once_with(["http/1.1"])

    def test_importing_the_module_does_not_start_the_server(self):
        with patch("uvicorn.run") as run:
            runpy.run_path(SCRIPT, run_name="run_https_imported")

        run.assert_not_called()
