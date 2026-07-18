from types import SimpleNamespace

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
    assert body["openai"]["model"] == "gpt-5.6-luna"
    assert body["openai"]["latest_global_generation"]["fallback_reason"] == "provider_error"
    assert body["openai"]["recent_technical_only_count"] == 1
    assert body["data_providers"]["sec_edgar"] == {
        "configured": False,
        "mode": "read_only",
        "cache": {
            "status": "not_configured",
            "entry_count": 0,
            "size_bytes": 0,
            "max_entries": 0,
            "max_size_bytes": 0,
            "utilization_percent": 0.0,
        },
    }
    assert body["data_providers"]["fred"] == {
        "configured": False,
        "mode": "read_only",
    }
    assert body["advisory_jobs"] == {
        "active_count": 0,
        "queued_count": 0,
        "max_workers": 0,
    }


def test_system_status_reports_database_model_override():
    repository = InMemoryRepository()
    repository.upsert_settings({"ai_model": "gpt-5.6-sol"})
    client = TestClient(create_app(repository=repository))

    response = client.get(
        "/api/system/status",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 200
    assert response.json()["openai"]["model"] == "gpt-5.6-sol"


def test_startup_upgrades_legacy_default_model_without_manual_migration(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    repository = InMemoryRepository()
    repository.upsert_settings({"ai_model": "gpt-5.4-mini"})

    app = create_app(repository=repository)

    assert repository.get_settings()["ai_model"] == "gpt-5.6-luna"
    assert app.state.application_settings.ai_model == "gpt-5.6-luna"


def test_settings_update_refreshes_advisory_model_without_restart():
    repository = InMemoryRepository()
    app = create_app(repository=repository)
    app.state.advisory_narrative_provider = SimpleNamespace(model="gpt-5.4-mini")

    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            headers={"Authorization": "Bearer test-api-token"},
            json={"ai_model": "gpt-5.6-luna"},
        )
        status_response = client.get(
            "/api/system/status",
            headers={"Authorization": "Bearer test-api-token"},
        )

    assert response.status_code == 200
    assert response.json()["ai_model"] == "gpt-5.6-luna"
    assert app.state.advisory_narrative_provider.model == "gpt-5.6-luna"
    assert status_response.json()["openai"]["model"] == "gpt-5.6-luna"


def test_system_status_isolated_from_sec_cache_observability_failure():
    class BrokenCacheProvider:
        max_persistent_entries = 256
        max_persistent_bytes = 1024

        @staticmethod
        def cache_status():
            raise OSError("cache directory unavailable")

    app = create_app(repository=InMemoryRepository())
    app.state.advisory_filing_provider = BrokenCacheProvider()

    response = TestClient(app).get(
        "/api/system/status",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 200
    assert response.json()["data_providers"]["sec_edgar"]["cache"] == {
        "status": "unavailable",
        "entry_count": 0,
        "size_bytes": 0,
        "max_entries": 256,
        "max_size_bytes": 1024,
        "utilization_percent": 0.0,
    }
