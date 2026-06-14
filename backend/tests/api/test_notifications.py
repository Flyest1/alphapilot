from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.services.report_service import ReportService

AUTH = {"Authorization": "Bearer test-api-token"}
SCHEDULER_AUTH = {"Authorization": "Bearer test-scheduler-token"}


def test_notification_list_and_read_state_endpoints():
    repository = InMemoryRepository()
    row = repository.create_notification(
        {
            "event_key": "report_completed:1",
            "event_type": "report_completed",
            "title": "완료",
            "message": "리포트 완료",
        }
    )
    client = TestClient(create_app(repository=repository))

    response = client.get("/api/notifications", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["unread_count"] == 1

    read = client.post(f"/api/notifications/{row['id']}/read", headers=AUTH)
    assert read.status_code == 200
    assert read.json()["is_read"] is True

    response = client.get("/api/notifications", headers=AUTH)
    assert response.json()["unread_count"] == 0


def test_notification_read_all_and_missing_notification():
    repository = InMemoryRepository()
    for index in range(2):
        repository.create_notification(
            {
                "event_key": f"event:{index}",
                "event_type": "cycle_closed",
                "title": "종료",
                "message": "cycle 종료",
            }
        )
    client = TestClient(create_app(repository=repository))

    response = client.post("/api/notifications/read-all", headers=AUTH)
    assert response.json()["updated_count"] == 2
    assert client.post("/api/notifications/missing/read", headers=AUTH).status_code == 404


def test_only_scheduled_report_generation_creates_notifications(monkeypatch):
    monkeypatch.setattr(
        ReportService,
        "generate_report",
        lambda _self, report_type: {"id": f"{report_type}-report", "report_type": report_type},
    )
    scheduled_repository = InMemoryRepository()
    scheduled_client = TestClient(create_app(repository=scheduled_repository))
    manual_repository = InMemoryRepository()
    manual_client = TestClient(create_app(repository=manual_repository))

    scheduled_client.post("/api/reports/domestic/generate", headers=SCHEDULER_AUTH)
    manual_client.post("/api/reports/domestic/manual-generate", headers=AUTH)

    assert [row["event_type"] for row in scheduled_repository.list_notifications()] == [
        "report_completed"
    ]
    assert manual_repository.list_notifications() == []
