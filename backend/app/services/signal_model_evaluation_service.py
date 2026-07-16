"""Read-only signal-model evaluation status aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import Repository
from app.models.signal_model import (
    SignalModelActiveEvaluation,
    SignalModelEvaluationResponse,
    SignalModelSamples,
    SignalModelVersionReference,
)
from app.utils.logging import log_external_failure


class SignalModelEvaluationUnavailableError(RuntimeError):
    """Raised when evaluation storage fails for a reason other than a missing migration."""


class SignalModelEvaluationService:
    """Read persisted shadow-evaluation status without creating or changing records."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def get_evaluation(self) -> SignalModelEvaluationResponse:
        try:
            versions = self.repository.list_signal_model_versions()
            assignments = self.repository.list_signal_model_assignments()
            runs = self.repository.list_signal_model_evaluation_runs()
            report_links = self.repository.list_signal_model_report_links()
        except Exception as exc:
            log_external_failure(
                "signal_model_evaluation",
                exc,
                {"operation": "load_evaluation_records"},
            )
            if self._is_missing_relation(exc):
                return self._migration_required_response()
            raise SignalModelEvaluationUnavailableError(
                "signal model evaluation storage is unavailable"
            ) from exc

        version_by_id = {str(row.get("id")): row for row in versions if row.get("id") is not None}
        champion = self._version_reference(
            self._current_assignment(assignments, "champion"), version_by_id
        )
        challenger = self._version_reference(
            self._current_assignment(assignments, "challenger"), version_by_id
        )
        samples = SignalModelSamples(
            official_scheduled=sum(
                row.get("generation_source") == "scheduled" and row.get("is_official_sample")
                for row in report_links
            ),
            manual_input_links=sum(
                row.get("generation_source") == "manual" for row in report_links
            ),
        )
        active_evaluation = self._active_evaluation(runs, champion, challenger)

        if champion is None:
            return SignalModelEvaluationResponse(
                availability="available",
                state="unavailable",
                samples=samples,
            )
        if challenger is None:
            return SignalModelEvaluationResponse(
                availability="available",
                state="not_configured",
                champion=champion,
                challenger=challenger,
                samples=samples,
            )
        if active_evaluation is None:
            state = "not_configured"
        elif active_evaluation.status == "review_ready":
            state = "review_ready"
        elif active_evaluation.status == "failed":
            state = "unavailable"
        else:
            state = "collecting"
        return SignalModelEvaluationResponse(
            availability="available",
            state=state,
            champion=champion,
            challenger=challenger,
            active_evaluation=active_evaluation,
            samples=samples,
        )

    @staticmethod
    def _current_assignment(
        assignments: Iterable[dict[str, Any]], role: str
    ) -> dict[str, Any] | None:
        active = [
            row for row in assignments if row.get("role") == role and row.get("ended_at") is None
        ]
        return max(
            active,
            key=lambda row: str(row.get("effective_at") or row.get("created_at") or ""),
            default=None,
        )

    @staticmethod
    def _version_reference(
        assignment: dict[str, Any] | None,
        version_by_id: dict[str, dict[str, Any]],
    ) -> SignalModelVersionReference | None:
        if assignment is None:
            return None
        version = version_by_id.get(str(assignment.get("model_version_id")))
        if version is None:
            return None
        required_fields = ("id", "model_key", "version", "config_sha256")
        if any(version.get(field) is None for field in required_fields):
            return None
        return SignalModelVersionReference(
            id=str(version["id"]),
            model_key=str(version["model_key"]),
            version=str(version["version"]),
            config_sha256=str(version["config_sha256"]),
        )

    @staticmethod
    def _active_evaluation(
        runs: Iterable[dict[str, Any]],
        champion: SignalModelVersionReference | None,
        challenger: SignalModelVersionReference | None,
    ) -> SignalModelActiveEvaluation | None:
        if champion is None or challenger is None:
            return None
        active_rows = [
            row
            for row in runs
            if str(row.get("champion_model_version_id")) == champion.id
            and str(row.get("challenger_model_version_id")) == challenger.id
            and row.get("status") in {"pending", "collecting", "review_ready", "failed"}
        ]
        if not active_rows:
            return None
        row = max(active_rows, key=lambda item: str(item.get("created_at") or ""))
        required_fields = (
            "id",
            "report_type",
            "trigger_type",
            "decision_at",
            "started_at",
            "ends_at",
            "status",
        )
        if any(row.get(field) is None for field in required_fields):
            raise SignalModelEvaluationUnavailableError(
                "active evaluation is missing required audit fields"
            )
        if row.get("status") == "review_ready":
            completed_at = row.get("completed_at")
            try:
                completed = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
                ends_at = datetime.fromisoformat(str(row["ends_at"]).replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise SignalModelEvaluationUnavailableError(
                    "review-ready evaluation has invalid completion timestamps"
                ) from exc
            if completed.tzinfo is None or ends_at.tzinfo is None:
                raise SignalModelEvaluationUnavailableError(
                    "review-ready evaluation timestamps must include a timezone"
                )
            if completed < ends_at:
                raise SignalModelEvaluationUnavailableError(
                    "review-ready evaluation completed before the 12-week window"
                )
            if ends_at.tzinfo is None or datetime.now(timezone.utc) < ends_at:
                raise SignalModelEvaluationUnavailableError(
                    "review-ready evaluation was exposed before the 12-week window"
                )
        return SignalModelActiveEvaluation(
            id=str(row["id"]),
            report_type=str(row["report_type"]),
            trigger_type=row["trigger_type"],
            decision_at=str(row["decision_at"]),
            started_at=str(row["started_at"]),
            ends_at=str(row["ends_at"]),
            status=row["status"],
            expected_observation_count=int(row.get("expected_observation_count") or 0),
            observed_observation_count=int(row.get("observed_observation_count") or 0),
            excluded_observation_count=int(row.get("excluded_observation_count") or 0),
        )

    @staticmethod
    def _is_missing_relation(exc: BaseException) -> bool:
        message = str(exc).casefold()
        code = str(getattr(exc, "code", "") or "").upper()
        if code in {"42P01", "PGRST205"}:
            return True
        relation_names = (
            "signal_model_versions",
            "signal_model_assignments",
            "signal_model_evaluation_runs",
            "signal_model_report_links",
        )
        if not any(relation in message for relation in relation_names):
            return False
        return (
            "does not exist" in message
            or "could not find the table" in message
            or "could not find table" in message
            or "schema cache" in message
            and "table" in message
        )

    @staticmethod
    def _migration_required_response() -> SignalModelEvaluationResponse:
        return SignalModelEvaluationResponse(
            availability="migration_required",
            state="unavailable",
            samples=SignalModelSamples(),
        )
