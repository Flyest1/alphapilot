"""Candidate universe refresh using only approved pykrx/yfinance providers."""

from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import Repository
from app.utils.logging import log_external_failure

KR_MARKET_CAP_LIMIT = 30
MAJOR_ETFS = (
    "VOO",
    "SPY",
    "QQQ",
    "SMH",
    "SCHD",
    "VTI",
    "IWM",
    "XLK",
    "GLD",
    "TLT",
)


class CandidateUniverseService:
    def __init__(
        self,
        repository: Repository,
        kr_provider: Any | None = None,
        yf_module: Any | None = None,
        now_provider: Any | None = None,
    ) -> None:
        self.repository = repository
        self.kr_provider = kr_provider
        self.yf_module = yf_module
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def refresh(self) -> dict[str, Any]:
        refreshed_at = self.now_provider().isoformat()
        kr_rows = self._refresh_kr(refreshed_at)
        etf_rows = self._refresh_etfs(refreshed_at)
        return {
            "refreshed_at": refreshed_at,
            "domestic_upserted": len(kr_rows),
            "global_etf_upserted": len(etf_rows),
            "total_active": len(self.repository.list_candidate_universe()),
        }

    def _refresh_kr(self, refreshed_at: str) -> list[dict[str, Any]]:
        provider = self._kr_provider()
        date_text = self.now_provider().strftime("%Y%m%d")
        try:
            nearest = provider.get_nearest_business_day_in_a_week(date_text)
            frame = provider.get_market_cap_by_ticker(nearest, market="ALL")
        except Exception as exc:
            log_external_failure("pykrx", exc, {"operation": "refresh_candidate_universe"})
            return []
        if frame is None or frame.empty:
            return []
        market_cap_column = "시가총액" if "시가총액" in frame.columns else frame.columns[0]
        tickers = (
            frame.sort_values(market_cap_column, ascending=False).head(KR_MARKET_CAP_LIMIT).index
        )
        rows = []
        for rank, ticker in enumerate(tickers, start=1):
            ticker_text = str(ticker)
            try:
                name = provider.get_market_ticker_name(ticker_text) or ticker_text
            except Exception:
                name = ticker_text
            rows.append(
                self.repository.upsert_candidate_universe(
                    {
                        "report_type": "domestic",
                        "market": "KR",
                        "ticker": ticker_text,
                        "name": name,
                        "currency": "KRW",
                        "source": "pykrx_market_cap",
                        "source_rank": rank,
                        "is_active": True,
                        "refreshed_at": refreshed_at,
                    }
                )
            )
        return rows

    def _refresh_etfs(self, refreshed_at: str) -> list[dict[str, Any]]:
        rows = []
        yf = self._yf_module()
        for rank, ticker in enumerate(MAJOR_ETFS, start=1):
            try:
                info = yf.Ticker(ticker).info or {}
                name = info.get("longName") or info.get("shortName") or ticker
            except Exception as exc:
                log_external_failure(
                    "yfinance",
                    exc,
                    {"operation": "refresh_candidate_etf", "ticker": ticker},
                )
                name = ticker
            rows.append(
                self.repository.upsert_candidate_universe(
                    {
                        "report_type": "global",
                        "market": "ETF",
                        "ticker": ticker,
                        "name": name,
                        "currency": "USD",
                        "source": "yfinance_major_etf",
                        "source_rank": rank,
                        "is_active": True,
                        "refreshed_at": refreshed_at,
                    }
                )
            )
        return rows

    def _kr_provider(self) -> Any:
        if self.kr_provider is None:
            from pykrx import stock

            self.kr_provider = stock
        return self.kr_provider

    def _yf_module(self) -> Any:
        if self.yf_module is None:
            import yfinance as yf

            self.yf_module = yf
        return self.yf_module
