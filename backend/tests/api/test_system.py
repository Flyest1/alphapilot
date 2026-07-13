from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app


def test_system_status_endpoint_reports_operational_counts():
    repository = InMemoryRepository()
    repository.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 1,
            "avg_price": 100,
            "currency": "KRW",
        }
    )
    repository.create_candidate_asset(
        {
            "market": "US",
            "ticker": "QQQ",
            "name": "Invesco QQQ Trust",
            "currency": "USD",
            "is_active": True,
        }
    )
    repository.create_report(
        {
            "report_type": "global",
            "title": "Global report",
            "summary": "summary",
            "content": {},
            "report_inputs": {
                "ai_generation": {
                    "mode": "technical_only",
                    "fallback_reason": "provider_error",
                }
            },
        }
    )
    test_client = TestClient(create_app(repository=repository))

    response = test_client.get(
        "/api/system/status",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["backend"]["status"] == "ok"
    assert body["database"]["status"] == "ok"
    assert body["assets"]["total_count"] == 1
    assert body["candidate_assets"]["active_count"] == 1
    assert body["reports"]["total_count"] == 1
    assert body["reports"]["latest_global_created_at"]
    assert body["scheduler"]["domestic"]["status"] in {"ok", "pending", "late"}
    assert body["scheduler"]["global"]["last_expected_at"]
    assert body["security"]["tokens_distinct"] is True
    assert body["openai"]["latest_global_generation"]["mode"] == "technical_only"
    assert body["openai"]["latest_global_generation"]["fallback_reason"] == "provider_error"
    assert body["openai"]["recent_technical_only_count"] == 1
