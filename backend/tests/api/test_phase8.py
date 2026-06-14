from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.services.backtest_service import RuleBacktestService
from app.services.candidate_universe_service import CandidateUniverseService

AUTH = {"Authorization": "Bearer test-api-token"}
SCHEDULER_AUTH = {"Authorization": "Bearer test-scheduler-token"}


def test_candidate_universe_refresh_uses_scheduler_token(monkeypatch):
    monkeypatch.setattr(
        CandidateUniverseService,
        "refresh",
        lambda _self: {"domestic_upserted": 1, "global_etf_upserted": 1, "total_active": 2},
    )
    client = TestClient(create_app(repository=InMemoryRepository()))

    assert client.post("/api/candidate-universe/refresh", headers=AUTH).status_code == 401
    response = client.post("/api/candidate-universe/refresh", headers=SCHEDULER_AUTH)

    assert response.status_code == 200
    assert response.json()["total_active"] == 2


def test_rule_backtest_endpoint_is_user_token_protected(monkeypatch):
    monkeypatch.setattr(
        RuleBacktestService,
        "run",
        lambda _self, report_type, limit: {
            "report_type": report_type,
            "tickers_tested": [],
            "sample_count": 0,
            "groups": [],
            "limit": limit,
        },
    )
    client = TestClient(create_app(repository=InMemoryRepository()))

    assert client.post("/api/backtests/rules/run").status_code == 401
    response = client.post(
        "/api/backtests/rules/run?report_type=domestic&limit=5",
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["report_type"] == "domestic"
    assert response.json()["limit"] == 5
