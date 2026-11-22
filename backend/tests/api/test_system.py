from datetime import datetime
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from app.api import system
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
    assert body["scheduler"]["domestic"]["status"] in {"pending", "missing"}
    assert body["scheduler"]["global"]["last_expected_at"]
    assert body["security"]["tokens_distinct"] is True
    assert body["openai"]["latest_global_generation"]["mode"] == "technical_only"
    assert body["openai"]["model"] == "gpt-6-luna"
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


@pytest.mark.parametrize("legacy_model", ["gpt-5.4-mini", "gpt-5.6-luna"])
def test_startup_upgrades_legacy_default_model_without_manual_migration(monkeypatch, legacy_model):
    monkeypatch.setenv("OPENAI_MODEL", legacy_model)
    repository = InMemoryRepository()
    repository.upsert_settings({"ai_model": legacy_model})

    app = create_app(repository=repository)

    assert repository.get_settings()["ai_model"] == "gpt-6-luna"
    assert app.state.application_settings.ai_model == "gpt-6-luna"


def test_settings_update_refreshes_advisory_model_without_restart():
    repository = InMemoryRepository()
    app = create_app(repository=repository)
    app.state.advisory_narrative_provider = SimpleNamespace(model="gpt-5.4-mini")

    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            headers={"Authorization": "Bearer test-api-token"},
            json={"ai_model": "gpt-6-luna"},
        )
        status_response = client.get(
            "/api/system/status",
            headers={"Authorization": "Bearer test-api-token"},
        )

    assert response.status_code == 200
    assert response.json()["ai_model"] == "gpt-6-luna"
    assert app.state.advisory_narrative_provider.model == "gpt-6-luna"
    assert status_response.json()["openai"]["model"] == "gpt-6-luna"


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


@pytest.mark.parametrize("legacy_model", ["gpt-5.4-mini", "gpt-5.6-luna"])
def test_startup_upgrades_legacy_env_default_without_settings_row(monkeypatch, legacy_model):
    monkeypatch.setenv("OPENAI_MODEL", legacy_model)
    app = create_app(repository=InMemoryRepository())
    assert app.state.application_settings.ai_model == "gpt-6-luna"


def _read_schedule(repository, monkeypatch, now):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(now).astimezone(tz)

    monkeypatch.setattr(system, "datetime", FixedDateTime)
    response = TestClient(create_app(repository=repository)).get(
        "/api/system/status", headers={"Authorization": "Bearer test-api-token"}
    )
    assert response.status_code == 200
    return response.json()


def test_weekend_schedule_uses_only_matching_receipts_and_preserves_late_completion(monkeypatch):
    repo = InMemoryRepository()
    repo.create_report_job(
        {
            "report_type": "global",
            "generation_source": "scheduled",
            "status": "completed",
            "created_at": "2026-11-20T21:26:13.12345Z",
            "updated_at": "2026-11-20T21:31:02Z",
        }
    )
    for _ in range(25):
        repo.create_report_job(
            {
                "report_type": "global",
                "generation_source": "manual",
                "status": "completed",
                "created_at": "2026-11-21T07:00:00Z",
            }
        )
    repo.create_report_job(
        {
            "report_type": "domestic",
            "generation_source": "scheduled",
            "status": "completed",
            "created_at": "2026-11-19T12:00:00+09:00",
        }
    )
    # A legacy row and a newly generated report are not evidence of a scheduled receipt.
    repo.create_report_job(
        {
            "report_type": "domestic",
            "status": "completed",
            "created_at": "2026-11-20T13:18:00+09:00",
        }
    )
    repo.create_report({"report_type": "domestic", "created_at": "2026-11-20T13:18:00+09:00"})
    body = _read_schedule(repo, monkeypatch, "2026-11-22T01:00:00+09:00")
    domestic, global_ = body["scheduler"]["domestic"], body["scheduler"]["global"]
    assert domestic["status"] == "missing"
    assert domestic["last_expected_at"] == "2026-11-20T08:30:00+09:00"
    assert domestic["latest_created_at"] == "2026-11-20T13:18:00+09:00"
    assert domestic["received_at"] is domestic["completed_at"] is None
    assert global_["last_expected_at"] == "2026-11-20T22:30:00+09:00"
    assert global_["status"] == "late_completed"
    assert global_["is_ok"] is False
    assert global_["received_at"] == "2026-11-21T06:26:13.123450+09:00"
    assert global_["completed_at"] == "2026-11-21T06:31:02+09:00"
    assert global_["receipt_delay_minutes"] == 476


@pytest.mark.parametrize(
    "job_state, created, updated, expected",
    [
        ("queued", "08:37:00", "08:37:00", "queued"),
        ("running", "08:37:00", "08:40:00", "running"),
        ("failed", "08:37:00", "08:40:00", "failed"),
        ("completed", "08:30:59", "08:39:00", "ok"),
        ("completed", "08:31:00", "08:39:00", "late_completed"),
        ("completed", "08:30:00", "14:30:01", "late_completed"),
    ],
)
def test_schedule_lifecycle(monkeypatch, job_state, created, updated, expected):
    repo = InMemoryRepository()
    repo.create_report_job(
        {
            "report_type": "domestic",
            "generation_source": "scheduled",
            "status": job_state,
            "created_at": f"2026-11-20T{created}+09:00",
            "updated_at": f"2026-11-20T{updated}+09:00",
        }
    )
    schedule = _read_schedule(repo, monkeypatch, "2026-11-20T15:00:00+09:00")["scheduler"][
        "domestic"
    ]
    assert schedule["status"] == expected
    assert (schedule["completed_at"] is not None) == (job_state == "completed")


def test_missing_receipt_grace_boundary_and_lookup_failure(monkeypatch):
    repo = InMemoryRepository()
    at_cutoff = _read_schedule(repo, monkeypatch, "2026-11-20T14:30:00+09:00")
    assert at_cutoff["scheduler"]["domestic"]["status"] == "pending"

    def broken(*_):
        raise RuntimeError("test database error")

    monkeypatch.setattr(repo, "latest_scheduled_job", broken)
    after_cutoff = _read_schedule(repo, monkeypatch, "2026-11-20T14:30:01+09:00")
    assert after_cutoff["scheduler"]["domestic"]["status"] == "unavailable"
    assert after_cutoff["database"]["status"] == "partial"
