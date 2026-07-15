import argparse
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.services.market_data_service import MarketDataResult

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "recalculate_recommendation_cycles.py"
)


def load_script_module():
    module_name = f"recalculate_recommendation_cycles_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def create_cycle(repository, **overrides):
    data = {
        "report_type": "global",
        "ticker": "AAPL",
        "name": "Apple",
        "action": "SELL",
        "horizon": "medium",
        "status": "active",
        "reference_price": 100,
        "target_price": 110,
        "stop_loss": 90,
        "started_at": "2026-01-01T00:00:00+00:00",
        "metadata": {},
    }
    data.update(overrides)
    return repository.create_recommendation_cycle(data)


def configure_script(module, monkeypatch, repository, backup_dir, apply):
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(apply=apply, limit=1000, backup_dir=backup_dir),
    )
    monkeypatch.setattr(module, "get_environment_settings", lambda: object())
    monkeypatch.setattr(module, "is_supabase_configured", lambda _environment: True)
    monkeypatch.setattr(module, "create_repository", lambda _environment: repository)


def read_audit(backup_dir):
    audit_path = next(backup_dir.glob("recommendation_cycles_recalculation_*.json"))
    return json.loads(audit_path.read_text(encoding="utf-8"))


def test_preview_writes_detailed_audit_but_console_has_safe_counts(tmp_path, monkeypatch, capsys):
    repository = InMemoryRepository()
    create_cycle(repository, ticker="PRIVATE-TICKER", target_price=90, stop_loss=80)
    module = load_script_module()
    configure_script(module, monkeypatch, repository, tmp_path, apply=False)

    assert module.main() == 0

    output = capsys.readouterr().out
    audit = read_audit(tmp_path)
    assert "PRIVATE-TICKER" not in output
    assert "target_price" not in output
    assert "quarantined=1" in output
    assert audit["mode"] == "preview"
    assert audit["layout_records"][0]["ticker"] == "PRIVATE-TICKER"
    assert audit["unresolved_malformed_rows"]


def test_preview_recognizes_already_quarantined_cycle(tmp_path, monkeypatch, capsys):
    repository = InMemoryRepository()
    create_cycle(
        repository,
        target_price=90,
        stop_loss=80,
        barrier_hit_at=None,
        metadata={
            "measurement_excluded": True,
            "measurement_exclusion_reason": "invalid_short_barrier_layout",
            "measurement_policy_version": "short_barrier_layout_v1",
        },
    )
    module = load_script_module()
    configure_script(module, monkeypatch, repository, tmp_path, apply=False)

    assert module.main() == 0

    output = capsys.readouterr().out
    audit = read_audit(tmp_path)
    assert "unresolved=0" in output
    assert audit["unresolved_malformed_rows"] == []


def test_apply_creates_backup_before_verified_normalization(tmp_path, monkeypatch):
    repository = InMemoryRepository()
    cycle = create_cycle(repository)
    module = load_script_module()
    configure_script(module, monkeypatch, repository, tmp_path, apply=True)

    class NormalizingTracker:
        def __init__(self, repo, _market_data_service):
            self.repository = repo

        def recalculate_recommendation_cycles(self, limit):
            self.repository.update_recommendation_cycle(
                cycle["id"],
                {
                    "target_price": 90,
                    "stop_loss": 110,
                    "metadata": {
                        "measurement_excluded": False,
                        "measurement_exclusion_reason": None,
                        "measurement_policy_version": "short_barrier_layout_v1",
                    },
                },
            )
            return 1

    monkeypatch.setattr(module, "PerformanceTracker", NormalizingTracker)

    assert module.main() == 0

    backup_path = next(tmp_path.glob("recommendation_cycles_[0-9]*.json"))
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    audit = read_audit(tmp_path)
    assert backup["cycles"][0]["target_price"] == 110
    assert audit["status"] == "verified"
    assert audit["unresolved_malformed_rows"] == []


def test_apply_rolls_back_partial_recalculation_failure(tmp_path, monkeypatch):
    repository = InMemoryRepository()
    cycle = create_cycle(
        repository, status="hit_target", barrier_hit_at="2026-01-02T00:00:00+00:00"
    )
    module = load_script_module()
    configure_script(module, monkeypatch, repository, tmp_path, apply=True)

    class FailingTracker:
        def __init__(self, repo, _market_data_service):
            self.repository = repo

        def recalculate_recommendation_cycles(self, limit):
            self.repository.update_recommendation_cycle(
                cycle["id"],
                {"status": "active", "barrier_hit_at": None, "metadata": {"changed": True}},
            )
            raise RuntimeError("simulated partial failure")

    monkeypatch.setattr(module, "PerformanceTracker", FailingTracker)

    assert module.main() == 1

    restored = repository.list_recommendation_cycles()[0]
    audit = read_audit(tmp_path)
    assert restored["status"] == "hit_target"
    assert restored["barrier_hit_at"] == "2026-01-02T00:00:00+00:00"
    assert restored["metadata"] == {}
    assert audit["status"] == "rolled_back"
    assert audit["rollback"]["restored_cycle_ids"] == [cycle["id"]]


def test_apply_fails_verification_when_expected_policy_is_missing(tmp_path, monkeypatch):
    repository = InMemoryRepository()
    create_cycle(repository)
    module = load_script_module()
    configure_script(module, monkeypatch, repository, tmp_path, apply=True)

    class NoopTracker:
        def __init__(self, _repo, _market_data_service):
            pass

        def recalculate_recommendation_cycles(self, limit):
            return 0

    monkeypatch.setattr(module, "PerformanceTracker", NoopTracker)

    assert module.main() == 1

    audit = read_audit(tmp_path)
    assert audit["status"] == "rolled_back"
    assert audit["unresolved_malformed_rows"] == [
        {
            "cycle_id": audit["layout_records"][0]["cycle_id"],
            "reason": "measurement_metadata_missing",
        }
    ]


def test_apply_verifies_quarantined_malformed_cycle(tmp_path, monkeypatch):
    repository = InMemoryRepository()
    cycle = create_cycle(
        repository,
        target_price=90,
        stop_loss=80,
        status="hit_target",
        barrier_hit_at="2026-01-02T00:00:00+00:00",
    )
    module = load_script_module()
    configure_script(module, monkeypatch, repository, tmp_path, apply=True)

    class QuarantiningTracker:
        def __init__(self, repo, _market_data_service):
            self.repository = repo

        def recalculate_recommendation_cycles(self, limit):
            self.repository.update_recommendation_cycle(
                cycle["id"],
                {
                    "status": "active",
                    "barrier_hit_at": None,
                    "metadata": {
                        "measurement_excluded": True,
                        "measurement_exclusion_reason": "invalid_short_barrier_layout",
                        "measurement_policy_version": "short_barrier_layout_v1",
                    },
                },
            )
            return 1

    monkeypatch.setattr(module, "PerformanceTracker", QuarantiningTracker)

    assert module.main() == 0

    audit = read_audit(tmp_path)
    assert audit["status"] == "verified"
    assert audit["layout_records"][0]["layout"] == "invalid"


def test_apply_persists_normalization_when_market_history_is_empty(tmp_path, monkeypatch):
    repository = InMemoryRepository()
    create_cycle(repository)
    module = load_script_module()
    configure_script(module, monkeypatch, repository, tmp_path, apply=True)

    class EmptyMarketDataService:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_price_history(self, *args, **kwargs):
            return MarketDataResult(pd.DataFrame(), None, True, "mock", "empty", None)

    monkeypatch.setattr(module, "MarketDataService", EmptyMarketDataService)

    assert module.main() == 0

    updated = repository.list_recommendation_cycles()[0]
    assert updated["target_price"] == 90
    assert updated["stop_loss"] == 110
    assert updated["metadata"]["measurement_excluded"] is False
