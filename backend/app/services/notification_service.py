"""Scheduled-report notification generation and optional Telegram delivery."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any
from urllib import request

from app.config import (
    get_env_application_defaults,
    get_environment_settings,
    resolve_application_settings,
)
from app.db.supabase_client import Repository
from app.services.portfolio_service import PortfolioService
from app.utils.labels import report_type_label
from app.utils.logging import log_external_failure

TELEGRAM_SETTING_BY_EVENT = {
    "report_completed": "telegram_notify_report_completed",
    "target_hit": "telegram_notify_target_hit",
    "stop_hit": "telegram_notify_stop_hit",
    "cycle_closed": "telegram_notify_cycle_closed",
    "drift_warning": "telegram_notify_drift_warning",
}


class TelegramSender:
    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        opener: Any | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.opener = opener or request.urlopen

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, title: str, message: str) -> bool:
        if not self.configured:
            return False
        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": f"[AlphaPilot] {title}\n{message}",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        req = request.Request(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener(req, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        return bool(body.get("ok"))


class NotificationService:
    def __init__(
        self,
        repository: Repository,
        market_data_service: Any | None = None,
        telegram_sender: TelegramSender | None = None,
    ) -> None:
        self.repository = repository
        self.market_data_service = market_data_service
        env = get_environment_settings()
        self.telegram_sender = telegram_sender or TelegramSender(
            env.telegram_bot_token,
            env.telegram_chat_id,
        )

    def capture_cycle_states(self) -> dict[str, str]:
        try:
            return {
                str(row["id"]): str(row.get("status") or "")
                for row in self.repository.list_recommendation_cycles(limit=1000)
            }
        except Exception as exc:
            log_external_failure("notifications", exc, {"operation": "capture_cycle_states"})
            return {}

    def create_scheduled_report_notifications(
        self,
        report: dict[str, Any],
        previous_cycle_states: dict[str, str],
    ) -> list[dict[str, Any]]:
        events = [self._report_completed_event(report)]
        events.extend(self._cycle_events(previous_cycle_states))
        events.extend(self._drift_events(report))
        created = []
        for event in events:
            row = self._persist_and_deliver(event)
            if row is not None:
                created.append(row)
        return created

    def _report_completed_event(self, report: dict[str, Any]) -> dict[str, Any]:
        report_type = str(report.get("report_type") or "")
        label = report_type_label(report_type)
        return {
            "event_key": f"report_completed:{report.get('id')}",
            "event_type": "report_completed",
            "title": f"{label} 리포트 생성 완료",
            "message": f"{label} 시장 리포트 생성이 완료되었습니다.",
            "severity": "info",
            "report_id": report.get("id"),
            "metadata": {"report_type": report_type},
        }

    def _cycle_events(self, previous_cycle_states: dict[str, str]) -> list[dict[str, Any]]:
        try:
            cycles = self.repository.list_recommendation_cycles(limit=1000)
        except Exception as exc:
            log_external_failure("notifications", exc, {"operation": "list_cycle_events"})
            return []
        events = []
        for cycle in cycles:
            cycle_id = str(cycle.get("id") or "")
            status = str(cycle.get("status") or "")
            previous = previous_cycle_states.get(cycle_id)
            if previous == status or status not in {
                "hit_target",
                "hit_stop",
                "expired",
                "superseded",
            }:
                continue
            ticker = str(cycle.get("ticker") or "")
            if status == "hit_target":
                event_type, title, message, severity = (
                    "target_hit",
                    f"{ticker} 목표가 도달",
                    "추천 cycle이 목표가에 도달했습니다. 이익 실현 또는 전략 재검토를 확인하세요.",
                    "positive",
                )
            elif status == "hit_stop":
                event_type, title, message, severity = (
                    "stop_hit",
                    f"{ticker} 손절가 도달",
                    "추천 cycle이 손절가에 도달했습니다. 손절 조건과 무효화 기준을 확인하세요.",
                    "warning",
                )
            else:
                event_type, title, message, severity = (
                    "cycle_closed",
                    f"{ticker} 추천 cycle 종료",
                    "추천 cycle이 기간 만료 또는 새 전략으로 대체되어 종료되었습니다.",
                    "info",
                )
            events.append(
                {
                    "event_key": f"{event_type}:{cycle_id}:{cycle.get('closed_at') or status}",
                    "event_type": event_type,
                    "title": title,
                    "message": message,
                    "severity": severity,
                    "cycle_id": cycle_id,
                    "report_id": cycle.get("report_id"),
                    "metadata": {"ticker": ticker, "status": status, "previous_status": previous},
                }
            )
        return events

    def _drift_events(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        if self.market_data_service is None:
            return []
        try:
            summary = PortfolioService(self.repository, self.market_data_service).get_summary()
        except Exception as exc:
            log_external_failure("notifications", exc, {"operation": "build_drift_events"})
            return []
        events = []
        for message in summary.rebalance_suggestions:
            digest = sha256(message.encode("utf-8")).hexdigest()[:16]
            events.append(
                {
                    "event_key": f"drift_warning:{report.get('id')}:{digest}",
                    "event_type": "drift_warning",
                    "title": "리밸런스 드리프트 경고",
                    "message": message,
                    "severity": "warning",
                    "report_id": report.get("id"),
                    "metadata": {},
                }
            )
        return events

    def _persist_and_deliver(self, event: dict[str, Any]) -> dict[str, Any] | None:
        try:
            if self.repository.get_notification_by_event_key(event["event_key"]):
                return None
            row = self.repository.create_notification(event)
        except Exception as exc:
            log_external_failure(
                "notifications",
                exc,
                {"operation": "create_notification", "event_type": event.get("event_type")},
            )
            return None
        try:
            settings = resolve_application_settings(
                self.repository.get_settings(),
                get_env_application_defaults(),
            )
        except Exception as exc:
            log_external_failure(
                "notifications",
                exc,
                {"operation": "resolve_notification_settings"},
            )
            updated = self.repository.update_notification(
                row["id"],
                {"telegram_status": "settings_unavailable"},
            )
            return updated or row
        enabled = bool(getattr(settings, TELEGRAM_SETTING_BY_EVENT[event["event_type"]]))
        status = "disabled"
        if enabled and not self.telegram_sender.configured:
            status = "not_configured"
        elif enabled:
            try:
                status = (
                    "delivered"
                    if self.telegram_sender.send(event["title"], event["message"])
                    else "failed"
                )
            except Exception as exc:
                status = "failed"
                log_external_failure(
                    "telegram",
                    RuntimeError("Telegram delivery failed"),
                    {
                        "operation": "send_notification",
                        "event_type": event.get("event_type"),
                        "error_type": type(exc).__name__,
                    },
                )
        updated = self.repository.update_notification(row["id"], {"telegram_status": status})
        return updated or row


def mark_notification_read(repository: Repository, notification_id: str) -> dict[str, Any] | None:
    return repository.update_notification(
        notification_id,
        {
            "is_read": True,
            "read_at": datetime.now(timezone.utc).isoformat(),
        },
    )
