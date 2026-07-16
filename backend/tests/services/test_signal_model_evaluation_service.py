import pytest

from app.db.supabase_client import InMemoryRepository
from app.services.report_service import ReportService
from app.services.signal_model_evaluation_service import (
    SignalModelEvaluationService,
    SignalModelEvaluationUnavailableError,
)


def _version(repository: InMemoryRepository, version: str) -> dict:
    return repository.create_signal_model_version(
        {
            "model_key": "technical_score",
            "version": version,
            "config": {"weights": {"trend": 30 if version == "v1" else 29}},
        }
    )


def test_champion_without_challenger_stays_not_configured_and_keeps_thresholds_unconfigured():
    repository = InMemoryRepository()
    champion = _version(repository, "v1")
    repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )

    result = SignalModelEvaluationService(repository).get_evaluation()

    assert result.availability == "available"
    assert result.state == "not_configured"
    assert result.champion is not None
    assert result.champion.id == champion["id"]
    assert result.challenger is None
    assert result.active_evaluation is None
    assert result.thresholds.state == "unconfigured"
    assert result.thresholds.values is None
    assert result.promotion.automatic is False
    assert result.promotion.eligible is None


def test_missing_champion_fails_closed_as_unavailable():
    result = SignalModelEvaluationService(InMemoryRepository()).get_evaluation()

    assert result.availability == "available"
    assert result.state == "unavailable"
    assert result.champion is None


def test_service_rejects_premature_review_ready_row_even_if_storage_is_forged():
    repository = InMemoryRepository()
    champion = _version(repository, "v1")
    challenger = _version(repository, "v2")
    repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )
    repository.create_signal_model_assignment(
        {"model_version_id": challenger["id"], "role": "challenger"}
    )
    repository.signal_model_evaluation_runs["forged-run"] = {
        "id": "forged-run",
        "champion_model_version_id": champion["id"],
        "challenger_model_version_id": challenger["id"],
        "report_type": "domestic",
        "trigger_type": "scheduled",
        "decision_at": "2026-07-17T00:00:00+00:00",
        "started_at": "2026-07-17T00:00:00+00:00",
        "ends_at": "2026-10-09T00:00:00+00:00",
        "completed_at": "2026-07-18T00:00:00+00:00",
        "status": "review_ready",
        "created_at": "2026-07-17T00:00:00+00:00",
    }

    with pytest.raises(SignalModelEvaluationUnavailableError, match="before the 12-week"):
        SignalModelEvaluationService(repository).get_evaluation()


def test_active_evaluation_is_only_exposed_for_the_current_champion_and_challenger_pair():
    repository = InMemoryRepository()
    champion = _version(repository, "v1")
    challenger = _version(repository, "v2")
    repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )
    repository.create_signal_model_assignment(
        {"model_version_id": challenger["id"], "role": "challenger"}
    )
    run = repository.create_signal_model_evaluation_run(
        {
            "champion_model_version_id": champion["id"],
            "challenger_model_version_id": challenger["id"],
            "report_type": "domestic",
            "trigger_type": "scheduled",
            "decision_at": "2026-07-17T00:00:00+00:00",
            "started_at": "2026-07-17T00:00:00+00:00",
            "status": "collecting",
            "input_snapshot": {"report_inputs": {"market": "KR"}},
            "expected_observation_count": 12,
            "observed_observation_count": 2,
        }
    )

    result = SignalModelEvaluationService(repository).get_evaluation()

    assert result.state == "collecting"
    assert result.active_evaluation is not None
    assert result.active_evaluation.id == run["id"]
    assert result.active_evaluation.ends_at == "2026-10-09T00:00:00+00:00"


def test_challenger_without_run_is_not_reported_as_collecting():
    repository = InMemoryRepository()
    champion = _version(repository, "v1")
    challenger = _version(repository, "v2")
    repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )
    repository.create_signal_model_assignment(
        {"model_version_id": challenger["id"], "role": "challenger"}
    )

    result = SignalModelEvaluationService(repository).get_evaluation()

    assert result.state == "not_configured"
    assert result.active_evaluation is None


def test_failed_evaluation_is_exposed_as_unavailable():
    repository = InMemoryRepository()
    champion = _version(repository, "v1")
    challenger = _version(repository, "v2")
    repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )
    repository.create_signal_model_assignment(
        {"model_version_id": challenger["id"], "role": "challenger"}
    )
    run = repository.create_signal_model_evaluation_run(
        {
            "champion_model_version_id": champion["id"],
            "challenger_model_version_id": challenger["id"],
            "report_type": "domestic",
            "trigger_type": "scheduled",
            "decision_at": "2026-07-17T00:00:00+00:00",
            "started_at": "2026-07-17T00:00:00+00:00",
            "status": "failed",
            "failure_reason": "data_gap",
            "input_snapshot": {},
        }
    )

    result = SignalModelEvaluationService(repository).get_evaluation()

    assert result.state == "unavailable"
    assert result.active_evaluation is not None
    assert result.active_evaluation.id == run["id"]
    assert result.active_evaluation.status == "failed"


def test_pipeline_report_link_uses_snapshot_and_never_breaks_report_success(monkeypatch):
    repository = InMemoryRepository()
    champion = _version(repository, "v1")
    assignment = repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )
    report = repository.create_report(
        {"report_type": "domestic", "title": "report", "summary": "summary", "content": {}}
    )
    service = ReportService(repository)
    inputs = {"market": {"provider": "mock"}}

    service._save_signal_model_report_link(report, inputs, "scheduled")

    link = repository.list_signal_model_report_links()[0]
    assert link["generation_source"] == "scheduled"
    assert link["is_official_sample"] is True
    assert link["champion_assignment_id"] == assignment["id"]
    assert link["report_inputs_snapshot"] == inputs

    monkeypatch.setattr(
        repository,
        "create_signal_model_report_link",
        lambda _data: (_ for _ in ()).throw(RuntimeError("link storage unavailable")),
    )
    service._save_signal_model_report_link(report, inputs, "manual")
