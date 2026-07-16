from pathlib import Path

import pytest

from app.db.supabase_client import InMemoryRepository, SupabaseRepository


class _InsertResponse:
    def __init__(self, data):
        self.data = data


class _InsertBuilder:
    def __init__(self):
        self.payload = None

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return _InsertResponse([self.payload])


class _InsertClient:
    def __init__(self):
        self.builder = _InsertBuilder()

    def table(self, _name):
        return self.builder


def _version(repository: InMemoryRepository, version: str, trend: int) -> dict:
    return repository.create_signal_model_version(
        {
            "model_key": "technical_score",
            "version": version,
            "config": {"weights": {"trend": trend}},
        }
    )


def test_signal_model_versions_are_copy_isolated_and_config_hashes_are_immutable():
    repository = InMemoryRepository()
    version = _version(repository, "v1", 30)

    version["config"]["weights"]["trend"] = 0

    assert repository.list_signal_model_versions()[0]["config"]["weights"]["trend"] == 30
    with pytest.raises(ValueError, match="already exists"):
        _version(repository, "v1", 30)
    with pytest.raises(ValueError, match="configuration already exists"):
        _version(repository, "v2", 30)


def test_signal_model_run_and_observation_enforce_audit_and_arm_isolation():
    repository = InMemoryRepository()
    champion = _version(repository, "v1", 30)
    challenger = _version(repository, "v2", 29)
    run = repository.create_signal_model_evaluation_run(
        {
            "champion_model_version_id": champion["id"],
            "challenger_model_version_id": challenger["id"],
            "report_type": "global",
            "trigger_type": "scheduled",
            "decision_at": "2026-07-17T00:00:00+00:00",
            "started_at": "2026-07-17T00:00:00+00:00",
            "input_snapshot": {"report_inputs": {"ticker": "QQQ"}},
        }
    )

    assert run["ends_at"] == "2026-10-09T00:00:00+00:00"
    assert run["champion_config_sha256"] == champion["config_sha256"]
    with pytest.raises(ValueError, match="does not match its arm"):
        repository.create_signal_model_evaluation_observation(
            {
                "evaluation_run_id": run["id"],
                "model_version_id": challenger["id"],
                "arm": "champion",
                "observation_key": "QQQ:2026-07-17",
                "observed_at": "2026-07-17T00:00:00+00:00",
                "market": "ETF",
                "ticker": "QQQ",
                "action": "WATCH",
                "horizon": "medium",
            }
        )
    observation = repository.create_signal_model_evaluation_observation(
        {
            "evaluation_run_id": run["id"],
            "model_version_id": champion["id"],
            "arm": "champion",
            "observation_key": "QQQ:2026-07-17",
            "observed_at": "2026-07-17T00:00:00+00:00",
            "market": "ETF",
            "ticker": "QQQ",
            "action": "WATCH",
            "horizon": "medium",
            "returns": {"1d": 1.2},
            "outcome_snapshot": {"status": "pending"},
        }
    )

    assert observation["returns"] == {"1d": 1.2}
    assert len(repository.list_signal_model_evaluation_observations()) == 1


def test_signal_model_evaluation_runs_accept_scheduled_samples_only():
    repository = InMemoryRepository()
    champion = _version(repository, "v1", 30)
    challenger = _version(repository, "v2", 29)

    with pytest.raises(ValueError, match="must be scheduled"):
        repository.create_signal_model_evaluation_run(
            {
                "champion_model_version_id": champion["id"],
                "challenger_model_version_id": challenger["id"],
                "report_type": "domestic",
                "trigger_type": "manual",
                "decision_at": "2026-07-17T00:00:00+00:00",
                "started_at": "2026-07-17T00:00:00+00:00",
                "input_snapshot": {},
            }
        )


def test_signal_model_evaluation_rejects_premature_review_ready_state():
    repository = InMemoryRepository()
    champion = _version(repository, "v1", 30)
    challenger = _version(repository, "v2", 29)

    with pytest.raises(ValueError, match="after the 12-week window"):
        repository.create_signal_model_evaluation_run(
            {
                "champion_model_version_id": champion["id"],
                "challenger_model_version_id": challenger["id"],
                "report_type": "domestic",
                "trigger_type": "scheduled",
                "decision_at": "2026-07-17T00:00:00+00:00",
                "started_at": "2026-07-17T00:00:00+00:00",
                "status": "review_ready",
                "completed_at": "2026-07-18T00:00:00+00:00",
                "input_snapshot": {},
            }
        )


def test_supabase_evaluation_run_prepares_hashes_and_fixed_window(monkeypatch):
    client = _InsertClient()
    repository = SupabaseRepository(client=client)
    versions = [
        {"id": "champion", "config_sha256": "a" * 64},
        {"id": "challenger", "config_sha256": "b" * 64},
    ]
    monkeypatch.setattr(repository, "list_signal_model_versions", lambda: versions)

    created = repository.create_signal_model_evaluation_run(
        {
            "champion_model_version_id": "champion",
            "challenger_model_version_id": "challenger",
            "report_type": "domestic",
            "trigger_type": "scheduled",
            "decision_at": "2026-07-17T00:00:00+00:00",
            "started_at": "2026-07-17T00:00:00+00:00",
            "input_snapshot": {"b": 2, "a": 1},
        }
    )

    assert created["ends_at"] == "2026-10-09T00:00:00+00:00"
    assert created["champion_config_sha256"] == "a" * 64
    assert created["challenger_config_sha256"] == "b" * 64
    assert len(created["input_sha256"]) == 64

    with pytest.raises(ValueError, match="input hash"):
        repository.create_signal_model_evaluation_run(
            {
                "champion_model_version_id": "champion",
                "challenger_model_version_id": "challenger",
                "report_type": "domestic",
                "trigger_type": "scheduled",
                "decision_at": "2026-07-17T00:00:00+00:00",
                "started_at": "2026-07-17T00:00:00+00:00",
                "input_snapshot": {},
                "input_sha256": "0" * 64,
            }
        )


def test_report_links_enforce_source_rules_and_canonical_input_hash():
    repository = InMemoryRepository()
    champion = _version(repository, "v1", 30)
    assignment = repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )
    report = repository.create_report(
        {"report_type": "domestic", "title": "report", "summary": "summary", "content": {}}
    )
    link = repository.create_signal_model_report_link(
        {
            "report_id": report["id"],
            "generation_source": "manual",
            "is_official_sample": False,
            "champion_assignment_id": assignment["id"],
            "champion_version_id": champion["id"],
            "report_inputs_snapshot": {"b": 2, "a": 1},
            "evaluation_id": None,
        }
    )

    assert len(link["input_sha256"]) == 64
    other_report = repository.create_report(
        {"report_type": "domestic", "title": "other", "summary": "summary", "content": {}}
    )
    with pytest.raises(ValueError, match="official"):
        repository.create_signal_model_report_link(
            {
                "report_id": other_report["id"],
                "generation_source": "scheduled",
                "is_official_sample": False,
                "champion_assignment_id": assignment["id"],
                "champion_version_id": champion["id"],
                "report_inputs_snapshot": {},
            }
        )


def test_migration_seeds_only_the_immutable_champion_and_no_evaluation():
    migration = Path("backend/app/db/migrations/016_create_signal_model_evaluations.sql").read_text(
        encoding="utf-8"
    )

    assert migration.count("insert into signal_model_versions") == 1
    assert "'initial_immutable_baseline'" in migration
    assert "insert into signal_model_evaluation_runs" not in migration
    assert "ends_at = started_at + interval '12 weeks'" in migration
    assert "status <> 'review_ready' or completed_at >= ends_at" in migration
    assert "existing technical_score/v1 does not match the immutable baseline" in migration
    assert "evaluation run config hashes do not match model versions" in migration
