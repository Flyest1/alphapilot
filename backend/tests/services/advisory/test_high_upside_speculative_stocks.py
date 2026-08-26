from datetime import datetime, timezone

import pandas as pd

from app.services.advisory.features.high_upside_speculative_stocks import (
    HighUpsideSpeculativeStocksAnalyzer,
)
from app.services.market_data_service import MarketDataResult


def _statement(values):
    return pd.DataFrame(
        values,
        columns=[pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31")],
    )


class FakeTicker:
    info = {
        "longName": "Example Therapeutics",
        "marketCap": 500_000_000,
        "sector": "Healthcare",
        "industry": "Biotechnology",
    }
    quarterly_financials = _statement(
        {
            pd.Timestamp("2026-06-30"): {"Total Revenue": 120},
            pd.Timestamp("2026-03-31"): {"Total Revenue": 100},
        }
    )
    quarterly_cashflow = _statement(
        {
            pd.Timestamp("2026-06-30"): {"Free Cash Flow": -20},
            pd.Timestamp("2026-03-31"): {"Free Cash Flow": -22},
        }
    )
    quarterly_balance_sheet = _statement(
        {
            pd.Timestamp("2026-06-30"): {
                "Cash And Cash Equivalents": 200,
                "Total Debt": 40,
            },
            pd.Timestamp("2026-03-31"): {
                "Cash And Cash Equivalents": 180,
                "Total Debt": 45,
            },
        }
    )


class FakeYFinance:
    @staticmethod
    def Ticker(_ticker):
        return FakeTicker()


class FakeMarketData:
    @staticmethod
    def fetch_price_history(_market, _ticker, _lookback):
        index = pd.date_range("2025-07-01", periods=260, freq="B")
        close = pd.Series(range(100, 360), index=index, dtype=float)
        frame = pd.DataFrame(
            {
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 200_000,
            },
            index=index,
        )
        return MarketDataResult(
            dataframe=frame,
            last_trading_date=datetime(2026, 6, 30, tzinfo=timezone.utc),
            is_stale=False,
            provider="yfinance",
            data_quality_note="ok",
            current_price=359,
        )


class FakeFilings:
    def __init__(self, text="Phase 2 clinical trial and strategic partnership"):
        self.text = text

    def list_recent_filings(self, *_args, **_kwargs):
        return [
            {
                "form": "10-Q",
                "filed_at": "2026-06-20",
                "accession_number": "0001",
                "url": "https://www.sec.gov/Archives/edgar/data/1/filing.txt",
                "text": self.text,
            }
        ]


def test_speculative_analyzer_keeps_candidates_as_watch_and_separates_risk_scores():
    result = HighUpsideSpeculativeStocksAnalyzer(
        FakeMarketData(), FakeYFinance(), filing_provider=FakeFilings()
    ).analyze(["EXM"], limit=5)

    row = result["rows"][0]
    assert row["candidate_eligible"] is True
    assert row["action"] == "WATCH"
    assert row["classification"] == "deeper_research_candidate"
    assert row["speculative_track"] == "biotech"
    assert row["cash_runway_quarters"] == 10.0
    assert row["asymmetric_opportunity_score"] != row["upside_evidence_score"]
    assert result["top_candidates"][0]["ticker"] == "EXM"
    assert result["screening_scope"]["private_startups_excluded"] is True


def test_speculative_analyzer_rejects_going_concern_instead_of_ranking_it():
    result = HighUpsideSpeculativeStocksAnalyzer(
        FakeMarketData(),
        FakeYFinance(),
        filing_provider=FakeFilings(
            "substantial doubt about our ability to continue as a going concern"
        ),
    ).analyze(["RISK"])

    row = result["rows"][0]
    assert row["candidate_eligible"] is False
    assert "going_concern_signal" in row["rejection_reasons"]
    assert result["top_candidates"] == []
    assert result["rejected_or_data_limited"][0]["ticker"] == "RISK"


def test_speculative_analyzer_fails_closed_when_cash_burn_evidence_is_missing():
    class MissingCashFlowTicker(FakeTicker):
        quarterly_cashflow = pd.DataFrame()

    class MissingCashFlowYFinance:
        @staticmethod
        def Ticker(_ticker):
            return MissingCashFlowTicker()

    result = HighUpsideSpeculativeStocksAnalyzer(
        FakeMarketData(), MissingCashFlowYFinance(), filing_provider=FakeFilings()
    ).analyze(["MISS"])

    row = result["rows"][0]
    assert row["candidate_eligible"] is False
    assert "free_cash_flow_unavailable" in row["rejection_reasons"]
