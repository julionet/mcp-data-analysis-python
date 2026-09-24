"""Script de teste manual dos services — rode com:
    python scripts/test_services_manual.py

Seção 1: VolumeGuardService (sem banco)
Seção 2: AnalysisService com mocks (sem banco)
Seção 3: AnalysisService com banco real (requer .env e Config DB rodando)
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Garante que o pacote analysis_app está no path quando rodado de qualquer cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from repositories.analysis_repo import Analysis, AnalysisStep
from repositories.data_source_repo import DataSource
from schemas.exceptions import VolumeExceededError
from services.analysis_service import AnalysisService
from services.volume_guard_service import VolumeGuardService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VERDE = "\033[92m"
VERMELHO = "\033[91m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{VERDE}  ✓ {msg}{RESET}")


def erro(msg: str) -> None:
    print(f"{VERMELHO}  ✗ {msg}{RESET}")


def secao(titulo: str) -> None:
    print(f"\n{'=' * 60}\n  {titulo}\n{'=' * 60}")


# ---------------------------------------------------------------------------
# Seção 1 — VolumeGuardService (puramente in-memory, sem banco)
# ---------------------------------------------------------------------------

async def testar_volume_guard() -> None:
    secao("Seção 1: VolumeGuardService")

    svc = VolumeGuardService(max_rows=100, max_size_kb=50)

    # 1a. check_row_count — dentro do limite
    adapter_mock = MagicMock()
    adapter_mock.execute_query = AsyncMock(return_value=50)
    count = await svc.check_row_count(adapter_mock, "SELECT COUNT(*) FROM t", {})
    assert count == 50
    ok(f"check_row_count dentro do limite → {count} linhas")

    # 1b. check_row_count — excede o limite
    adapter_mock.execute_query = AsyncMock(return_value=999)
    try:
        await svc.check_row_count(adapter_mock, "SELECT COUNT(*) FROM t", {})
        erro("Esperava VolumeExceededError mas não veio")
    except VolumeExceededError as exc:
        ok(f"check_row_count excedido detectado → {exc.estimated_rows} linhas estimadas")

    # 1c. check_serialized_size — dentro do limite
    resultado_pequeno = [{"id": i, "valor": 1.23} for i in range(10)]
    kb = svc.check_serialized_size(resultado_pequeno)
    ok(f"check_serialized_size dentro do limite → {kb:.2f} KB")

    # 1d. check_serialized_size — excede o limite
    svc_pequeno = VolumeGuardService(max_rows=100, max_size_kb=1)
    resultado_grande = [{"id": i, "payload": "x" * 200} for i in range(100)]
    try:
        svc_pequeno.check_serialized_size(resultado_grande)
        erro("Esperava VolumeExceededError mas não veio")
    except VolumeExceededError as exc:
        ok(f"check_serialized_size excedido detectado → {exc.estimated_size_kb:.2f} KB")

    # 1e. build_refinement_response
    exc = VolumeExceededError(estimated_rows=999, estimated_size_kb=200.5)
    resp = svc.build_refinement_response(exc)
    assert resp["status"] == "refinamento_necessario"
    assert resp["estimativa"]["linhas"] == 999
    ok(f"build_refinement_response → status='{resp['status']}'")


# ---------------------------------------------------------------------------
# Seção 2 — AnalysisService com mocks (sem banco real)
# ---------------------------------------------------------------------------

PARAMETERS = {
    "data_inicial": {"type": "date", "required": True, "description": "Data inicial"},
    "data_final": {"type": "date", "required": True, "description": "Data final"},
}

SQL = (
    "SELECT data, valor FROM vendas "
    "WHERE data BETWEEN :data_inicial AND :data_final ORDER BY data"
)


def _build_mocks(analysis_id=None, linhas_count=5):
    analysis_id = analysis_id or uuid4()
    data_source_id = uuid4()

    analysis = Analysis(
        id=analysis_id,
        name="vendas_por_periodo",
        description="Vendas por período",
        data_source_id=data_source_id,
        parameters=PARAMETERS,
        is_active=True,
    )

    step = AnalysisStep(
        id=uuid4(),
        analysis_id=analysis_id,
        step_order=1,
        step_type="query",
        definition={"sql": SQL, "params": ["data_inicial", "data_final"]},
    )

    data_source = DataSource(
        id=data_source_id,
        name="vendas_db_local",
        type="postgresql",
        connection_config={
            "host": "localhost",
            "port": 5432,
            "database": "data_db",
            "user": "chronus",
            "password": "cifrada",
            "sslmode": "prefer",
        },
        is_active=True,
    )

    dados_retornados = [{"data": "2024-01-0" + str(i + 1), "valor": float(i * 10)} for i in range(linhas_count)]

    analysis_repo = MagicMock()
    analysis_repo.get_by_id = AsyncMock(return_value=analysis)
    analysis_repo.get_steps = AsyncMock(return_value=[step])

    data_source_repo = MagicMock()
    data_source_repo.get_by_id = AsyncMock(return_value=data_source)

    adapter_mock = MagicMock()
    adapter_mock.connect = AsyncMock()
    adapter_mock.disconnect = AsyncMock()
    # COUNT(*) retorna linhas_count; SELECT retorna os dados
    adapter_mock.execute_query = AsyncMock(side_effect=[linhas_count, dados_retornados])

    return analysis_repo, data_source_repo, adapter_mock, analysis_id, dados_retornados


async def testar_analysis_service_mocks() -> None:
    secao("Seção 2: AnalysisService com mocks")

    # 2a. Execução bem-sucedida
    analysis_repo, data_source_repo, adapter_mock, analysis_id, dados = _build_mocks(linhas_count=5)
    volume_guard = VolumeGuardService(max_rows=100, max_size_kb=150)

    with (
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "services.analysis_service.AdapterFactory.create_adapter", return_value=adapter_mock
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "services.analysis_service.decrypt_password", return_value="senha_decifrada"
        ),
    ):
        svc = AnalysisService(analysis_repo, data_source_repo, volume_guard)
        resultado = await svc.execute(analysis_id, {"data_inicial": "2024-01-01", "data_final": "2024-01-31"})

    assert resultado["status"] == "success"
    assert len(resultado["data"]) == 5
    ok(f"execute bem-sucedido → {len(resultado['data'])} linhas retornadas")

    # 2b. Volume excedido → refinamento
    analysis_repo2, data_source_repo2, adapter_mock2, analysis_id2, _ = _build_mocks(linhas_count=5)
    adapter_mock2.execute_query = AsyncMock(side_effect=[9999])  # só o COUNT, já excede
    volume_guard_estrito = VolumeGuardService(max_rows=10, max_size_kb=150)

    with (
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "services.analysis_service.AdapterFactory.create_adapter", return_value=adapter_mock2
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "services.analysis_service.decrypt_password", return_value="senha_decifrada"
        ),
    ):
        svc2 = AnalysisService(analysis_repo2, data_source_repo2, volume_guard_estrito)
        resultado2 = await svc2.execute(analysis_id2, {"data_inicial": "2024-01-01", "data_final": "2024-12-31"})

    assert resultado2["status"] == "refinamento_necessario"
    ok(f"execute com volume excedido → status='{resultado2['status']}', linhas estimadas={resultado2['estimativa']['linhas']}")

    # 2c. Análise não encontrada
    analysis_repo3 = MagicMock()
    analysis_repo3.get_by_id = AsyncMock(return_value=None)
    data_source_repo3 = MagicMock()
    svc3 = AnalysisService(analysis_repo3, data_source_repo3, VolumeGuardService(100, 150))
    try:
        await svc3.execute(uuid4(), {})
        erro("Esperava AnalysisNotFoundError mas não veio")
    except __import__("schemas.exceptions", fromlist=["AnalysisNotFoundError"]).AnalysisNotFoundError as exc:
        ok(f"Análise não encontrada detectada → {exc}")

    # 2d. Parâmetros inválidos (data_final ausente)
    analysis_repo4, data_source_repo4, _, analysis_id4, _ = _build_mocks()
    svc4 = AnalysisService(analysis_repo4, data_source_repo4, VolumeGuardService(100, 150))
    try:
        await svc4.execute(analysis_id4, {"data_inicial": "2024-01-01"})  # falta data_final
        erro("Esperava InvalidParametersError mas não veio")
    except __import__("schemas.exceptions", fromlist=["InvalidParametersError"]).InvalidParametersError as exc:
        ok(f"Parâmetro inválido detectado → {exc}")


# ---------------------------------------------------------------------------
# Seção 3 — AnalysisService com banco real (opcional)
# ---------------------------------------------------------------------------

async def testar_com_banco_real() -> None:
    secao("Seção 3: AnalysisService com banco real")
    print("  (requer Config DB rodando e .env configurado)")

    try:
        from database.connection import config_db_adapter, connect_config_db, disconnect_config_db
        from repositories.analysis_repo import AnalysisRepository
        from repositories.data_source_repo import DataSourceRepository
        from config import settings

        await connect_config_db()
        print(f"  Conectado ao Config DB: {settings.postgres_config_host}:{settings.postgres_config_port}/{settings.postgres_config_database}")

        analysis_repo = AnalysisRepository(config_db_adapter)
        data_source_repo = DataSourceRepository(config_db_adapter)
        volume_guard = VolumeGuardService(
            max_rows=settings.default_max_result_rows,
            max_size_kb=settings.default_max_result_size_kb,
        )

        svc = AnalysisService(analysis_repo, data_source_repo, volume_guard)

        # Lista análises disponíveis
        analyses = await svc.get_all_analyses()
        ok(f"get_all_analyses → {len(analyses)} análise(s) encontrada(s)")

        for a in analyses:
            print(f"    → id={a.id}  name={a.name}")

        if analyses:
            primeira = analyses[0]
            print(f"\n  Executando '{primeira.name}' com parâmetros de exemplo...")
            print("  (ajuste os params abaixo para bater com o schema da análise)")
            # ↓ Edite os parâmetros conforme o schema da análise cadastrada
            params_exemplo = {
                "data_final": "2024-01-01",
                "data_inicial": "2024-01-31",
            }
            resultado = await svc.execute(primeira.id, params_exemplo)
            status = resultado.get("status")
            if status == "success":
                ok(f"Execução bem-sucedida → {len(resultado['data'])} linha(s)")
            else:
                ok(f"Resposta de refinamento → {resultado['mensagem'][:80]}...")

        await disconnect_config_db()

    except Exception as exc:
        erro(f"Banco real indisponível ou erro de configuração: {exc}")
        print("  Dica: verifique .env e se o docker-compose está rodando.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    await testar_volume_guard()
    await testar_analysis_service_mocks()
    await testar_com_banco_real()
    print(f"\n{'=' * 60}\n  Testes manuais concluídos.\n{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
