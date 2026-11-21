from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
from postgrest import SyncPostgrestClient

from app.db.supabase_client import InMemoryRepository, SupabaseRepository
from app.main import create_app


def test_report_list_keeps_display_data_but_details_keep_full_input_snapshot():
    repository = InMemoryRepository()
    inputs = {
        "ai_generation": {"mode": "ai_narrative"},
        "tickers": {"AAPL": {"provider": "yfinance", "price_lineage": {"raw_daily_bars": [1]}}},
        "news_context": {"status": "ok"},
    }
    report = repository.create_report(
        {
            "report_type": "global",
            "title": "Report",
            "summary": "Summary",
            "content": {"asset_strategies": []},
            "report_inputs": inputs,
        }
    )
    client = TestClient(create_app(repository=repository))
    headers = {"Authorization": "Bearer test-api-token"}

    summary = client.get("/api/reports", headers=headers).json()[0]
    detail = client.get(f"/api/reports/{report['id']}", headers=headers).json()
    latest = client.get("/api/reports/latest", headers=headers).json()["global"]

    assert summary["content"] == report["content"]
    assert summary["report_inputs"] == {"ai_generation": {"mode": "ai_narrative"}}
    assert detail["report_inputs"] == inputs
    assert latest["report_inputs"] == inputs
    assert repository.get_report(report["id"])["report_inputs"] == inputs


def test_supabase_report_list_avoids_heavy_snapshot_projection_and_keeps_all_pages():
    rows = [
        {
            "id": str(index),
            "report_type": "global",
            "title": "Report",
            "summary": "Summary",
            "created_at": "2026-11-13",
            "content": {"asset_strategies": []},
            "ai_generation": {"mode": "technical_only"},
        }
        for index in range(3)
    ]

    def handle(request):
        assert request.method == "GET"
        projection = request.url.params["select"]
        if projection == "*":
            return httpx.Response(
                500,
                json={
                    "code": "57014",
                    "message": "statement timeout",
                    "details": None,
                    "hint": None,
                },
            )
        assert set(projection.split(",")) == {
            "id",
            "report_type",
            "title",
            "summary",
            "content",
            "created_at",
            "ai_generation:report_inputs->ai_generation",
        }
        offset = int(request.url.params.get("offset", 0))
        # A server-side row cap below the requested page size must not hide history.
        return httpx.Response(200, json=deepcopy(rows[offset : offset + 2]))

    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        postgrest = SyncPostgrestClient("https://example.test/rest/v1", http_client=http_client)
        repository = SupabaseRepository(client=SimpleNamespace(table=postgrest.from_))
        result = repository.list_reports()

    assert [row["id"] for row in result] == ["0", "1", "2"]
    assert all(
        row["report_inputs"] == {"ai_generation": {"mode": "technical_only"}} for row in result
    )
    assert all("ai_generation" not in row for row in result)
