# F13 — imagem do app (contexto de build = analysis_app/).
#
# Python 3.13: é a versão em que a suíte (334 testes) foi validada; pyodbc>=5.2 e
# bcrypt>=5 têm wheel para ela (ARQUITETURA.md §5.1). Pin em bookworm porque o repositório
# da Microsoft abaixo é o de Debian 12.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ODBC Driver 18 for SQL Server (par do SQL Server 2022; decisão 6 da spec F13).
# O driver 18 usa Encrypt=yes por padrão; o SQLServerAdapter já envia
# TrustServerCertificate=yes quando sslmode é omitido/"prefer" (adapters/sqlserver.py).
# Oracle não precisa de nada aqui: oracledb roda em thin mode (F9 §7).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependências antes do código: camada em cache enquanto requirements.txt não mudar.
COPY requirements.txt .
RUN pip install -r requirements.txt

# .env, certs/ e .venv ficam de fora (ver .dockerignore): secrets e certificados
# entram só em runtime (env_file / volume somente leitura).
COPY . .

RUN useradd --system --no-create-home --uid 10001 appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 3000

# Com TLS_ENABLED=true (local) o endpoint é https com certificado mkcert, que não é
# confiado dentro do container — por isso -k. No remote (HTTP interno) o mesmo comando vale.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD if [ "$TLS_ENABLED" = "false" ]; then S=http; else S=https; fi; curl -fsk "$S://localhost:${SERVER_PORT:-3000}/health" || exit 1

CMD ["python", "run_https.py"]
