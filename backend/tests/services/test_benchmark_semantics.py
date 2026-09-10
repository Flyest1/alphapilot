from types import SimpleNamespace

import pandas as pd
import pytest

from app.db.supabase_client import InMemoryRepository
from app.services.benchmark_service import BenchmarkService
from app.services.report.persistence import ReportPersistence


class Prices:
    def fetch_major_indices(self, *_args, **_kwargs):
        return {}

    def fetch_price_history(self, *_args, **_kwargs):
        return SimpleNamespace(
            dataframe=pd.DataFrame(
                {"close": [100, 110]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"])
            )
        )


def test_comparison_labels_distinguish_price_changes_from_investment_returns():
    repo = InMemoryRepository()
    for day, value in [("2026-01-02", 100), ("2026-01-05", 200)]:
        repo.create_portfolio_snapshot(
            {"snapshot_date": day, "total_market_value": value, "report_type": "manual"}
        )
    repo.create_recommendation_cycle(
        {
            "ticker": "AAPL",
            "action": "SELL",
            "reference_price": 100,
            "started_at": "2026-01-01T00:00:00+00:00",
        }
    )
    result = BenchmarkService(repo, Prices()).get_return_series()
    series = {row["key"]: row for row in result["series"]}
    assert series["actual_portfolio"]["label"] == "보유자산 평가액 변화"
    assert series["actual_portfolio"]["cash_flow_adjusted"] is False
    assert series["alphapilot"]["label"] == "추천 이후 평균 가격 변화"
    assert series["alphapilot"]["investable_return"] is False
    assert series["alphapilot"]["points"][-1]["sample_count"] == 1
    assert series["alphapilot"]["points"][-1]["return_rate"] == 10


@pytest.mark.parametrize("status", ["partial", "unavailable", "stale"])
def test_report_does_not_persist_incomplete_valuation_as_zero_snapshot(status):
    repo = InMemoryRepository()
    ReportPersistence(repo).save_portfolio_snapshot(
        {"id": "report"}, "global", {"valuation_status": status}, "Asia/Seoul"
    )
    assert repo.list_portfolio_snapshots() == []
