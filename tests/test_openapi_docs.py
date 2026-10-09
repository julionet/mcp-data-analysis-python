"""F16 — documentação da API (Swagger/OpenAPI) — F16_API_DOCUMENTATION.md §6.1. Sem banco."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import Settings
from main import app, docs_urls
from routes.openapi_docs import OPENAPI_TAGS
from schemas import admin as admin_schemas
from schemas.admin import AdminError

ROOT = Path(__file__).resolve().parent.parent
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
PUBLIC_OPERATIONS = {("post", "/auth/token"), ("post", "/auth/revoke"), ("get", "/health")}


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def _operations(spec: dict):
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield method, path, operation


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


class TestSwaggerFlag:
    def test_setting_defaults_to_off(self):
        assert Settings.model_fields["docs_enabled"].default is False

    def test_docs_urls_off(self):
        assert docs_urls(False) == {"docs_url": None, "redoc_url": None, "openapi_url": None}

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_served_only_when_enabled(self, path):
        assert TestClient(FastAPI(**docs_urls(True))).get(path).status_code == 200
        assert TestClient(FastAPI(**docs_urls(False))).get(path).status_code == 404

    @pytest.mark.parametrize("value, expected", [("true", "/docs"), ("false", None)])
    def test_env_var_controls_the_real_app(self, value, expected):
        code = "import sys; sys.path.insert(0, 'src'); from main import app; print(app.docs_url)"
        env = {**os.environ, "DOCS_ENABLED": value}
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == str(expected)


class TestAuthorizeButton:
    def test_bearer_security_scheme_declared(self, spec):
        scheme = spec["components"]["securitySchemes"]["BearerToken"]
        assert scheme["type"] == "http"
        assert scheme["scheme"] == "bearer"

    def test_lock_only_on_authenticated_routes(self, spec):
        for method, path, operation in _operations(spec):
            if (method, path) in PUBLIC_OPERATIONS:
                assert "security" not in operation, (method, path)
            else:
                assert operation.get("security") == [{"BearerToken": []}], (method, path)

    @pytest.mark.parametrize("path", ["/admin/users", "/admin/executions", "/me"])
    def test_missing_token_keeps_the_project_401(self, path):
        """`auto_error=False`: o 403 do HTTPBearer não pode substituir o 401 do projeto."""
        response = TestClient(app).get(path)
        assert response.status_code == 401
        assert response.json() == {"error": "unauthorized", "message": "Token de acesso inválido ou ausente."}
        assert response.headers["www-authenticate"] == "Bearer"


class TestDocumentationCoverage:
    def test_info(self, spec):
        assert spec["info"]["title"] == "Análise de Dados Genérica com MCP — API HTTP"
        assert spec["info"]["version"] == "1.0.0"
        assert "docs/MCP.md" in spec["info"]["description"]
        assert not {"contact", "license"} & set(spec["info"])
        assert "servers" not in spec

    def test_every_operation_has_summary_description_and_declared_tag(self, spec):
        declared = {tag["name"] for tag in OPENAPI_TAGS}
        assert {tag["name"] for tag in spec["tags"]} == declared
        operations = list(_operations(spec))
        assert len(operations) >= 44
        for method, path, operation in operations:
            assert operation.get("summary"), (method, path)
            assert operation.get("description"), (method, path)
            assert operation.get("tags") and set(operation["tags"]) <= declared, (method, path)

    def test_every_admin_error_is_documented(self, spec):
        documented: set[tuple[int, str]] = set()
        for _, _, operation in _operations(spec):
            for status, response in operation["responses"].items():
                for slug in _slugs(response["description"]):
                    documented.add((int(status), slug))
        errors = [cls for cls in _all_subclasses(AdminError) if cls.__module__ == admin_schemas.__name__]
        assert len(errors) >= 25
        for cls in errors:
            assert (cls.status_code, cls.error) in documented, cls.__name__

    def test_admin_routes_document_401_and_403_and_me_documents_401(self, spec):
        for method, path, operation in _operations(spec):
            if path.startswith("/admin"):
                assert {"401", "403"} <= set(operation["responses"]), (method, path)
            elif path.startswith("/me"):
                assert "401" in operation["responses"], (method, path)
                assert "403" not in operation["responses"], (method, path)

    def test_auth_routes_document_their_errors(self, spec):
        token = spec["paths"]["/auth/token"]["post"]["responses"]
        assert {"400", "401"} <= set(token)
        revoke = spec["paths"]["/auth/revoke"]["post"]["responses"]
        assert {"401", "404"} <= set(revoke)

    def test_domain_422_also_describes_the_default_validation_body(self, spec):
        response = spec["paths"]["/admin/users"]["post"]["responses"]["422"]
        refs = {item["$ref"].rsplit("/", 1)[-1] for item in response["content"]["application/json"]["schema"]["anyOf"]}
        assert refs == {"ErrorResponse", "ValidationErrorBody"}

    def test_request_bodies_have_examples(self, spec):
        for name in ["TokenRequest", "UserCreate", "ProfileCreate", "DataSourceCreate", "AnalysisCreate"]:
            assert "example" in spec["components"]["schemas"][name], name


class TestNoSecretsInResponses:
    FORBIDDEN = {"password", "password_hash", "token_hash"}

    def test_response_models_never_expose_secrets(self, spec):
        schemas = spec["components"]["schemas"]
        seen: set[str] = set()

        def walk(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    name = node["$ref"].rsplit("/", 1)[-1]
                    if name not in seen:
                        seen.add(name)
                        walk(schemas[name])
                    return
                for key, value in node.items():
                    if key == "properties":
                        assert not self.FORBIDDEN & set(value), sorted(self.FORBIDDEN & set(value))
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for _, _, operation in _operations(spec):
            for status, response in operation["responses"].items():
                if status.startswith("2"):
                    walk(response.get("content", {}))
        assert "DataSourceDetail" in seen and "UserDetail" in seen


class TestMcpIsNotInOpenapi:
    def test_mcp_documented_only_in_markdown(self, spec):
        assert not [path for path in spec["paths"] if path.startswith("/mcp")]
        assert (ROOT / "docs" / "MCP.md").is_file()


class TestExportedFile:
    def test_in_sync_with_the_code(self):
        module_spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "scripts" / "export_openapi.py")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        committed = (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")
        assert committed == module.build_openapi_text(), (
            "docs/openapi.json desatualizado. Regenere com: .venv/bin/python scripts/export_openapi.py"
        )

    def test_is_valid_openapi_31(self):
        data = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
        assert data["openapi"].startswith("3.1")
        assert "BearerToken" in data["components"]["securitySchemes"]


def _slugs(description: str) -> list[str]:
    """Slugs entre crases depois de 'Slugs:' na descrição da resposta (gerada por openapi_docs.py)."""
    if "Slugs:" not in description:
        return []
    tail = description.split("Slugs:", 1)[1].split(".", 1)[0]
    return [part.strip().strip("`") for part in tail.split(",") if part.strip()]
