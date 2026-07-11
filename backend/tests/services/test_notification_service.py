from types import SimpleNamespace

from app.db.supabase_client import InMemoryRepository
from app.services.notification_service import NotificationService, TelegramSender
from app.services.portfolio_service import PortfolioService


class FakeTelegram:
    configured = True

    def __init__(self):
        self.messages = []

    def send(self, title, message):
        self.messages.append((title, message))
        return True


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return b'{"ok": true}'


def test_telegram_sender_gracefully_skips_when_unconfigured():
    assert TelegramSender(None, None).configured is False
    assert TelegramSender(None, None).send("title", "message") is False


def test_telegram_sender_posts_message_without_exposing_config_to_caller():
    calls = []

    def opener(req, timeout):
        calls.append((req, timeout))
        return FakeResponse()

    sender = TelegramSender("secret-token", "chat-1", opener=opener)

    assert sender.send("완료", "메시지") is True
    assert calls[0][1] == 10
    assert b"chat-1" in calls[0][0].data


def test_scheduled_notifications_create_events_and_deliver_opted_in_telegram(monkeypatch):
    repository = InMemoryRepository()
    repository.upsert_settings(
        {
            "telegram_notify_report_completed": True,
            "telegram_notify_target_hit": True,
            "telegram_notify_drift_warning": True,
        }
    )
    cycle = repository.create_recommendation_cycle(
        {
            "report_type": "domestic",
            "ticker": "005930",
            "status": "active",
            "action": "BUY",
            "horizon": "medium",
        }
    )
    telegram = FakeTelegram()
    service = NotificationService(
        repository,
        market_data_service=object(),
        telegram_sender=telegram,
    )
    previous = service.capture_cycle_states()
    repository.update_recommendation_cycle(
        cycle["id"],
        {"status": "hit_target", "closed_at": "2026-06-14T00:00:00+00:00"},
    )
    monkeypatch.setattr(
        PortfolioService,
        "get_summary",
        lambda _self: SimpleNamespace(rebalance_suggestions=["현금 비중이 목표보다 높습니다."]),
    )

    created = service.create_scheduled_report_notifications(
        {"id": "report-1", "report_type": "domestic"},
        previous,
    )

    assert {row["event_type"] for row in created} == {
        "report_completed",
        "target_hit",
        "drift_warning",
    }
    assert all(row["telegram_status"] == "delivered" for row in created)
    assert len(telegram.messages) == 3
    assert (
        service.create_scheduled_report_notifications(
            {"id": "report-1", "report_type": "domestic"},
            previous,
        )
        == []
    )


def test_ambiguous_cycle_creates_cycle_closed_warning():
    repository = InMemoryRepository()
    cycle = repository.create_recommendation_cycle(
        {
            "report_type": "global",
            "ticker": "AAPL",
            "status": "ambiguous",
            "action": "BUY",
            "horizon": "medium",
        }
    )
    service = NotificationService(repository, market_data_service=object())

    events = service._cycle_events({cycle["id"]: "active"})

    assert len(events) == 1
    assert events[0]["event_type"] == "cycle_closed"
    assert events[0]["severity"] == "warning"
    assert "판정 보류" in events[0]["title"]
