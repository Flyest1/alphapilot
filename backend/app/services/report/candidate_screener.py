"""보유 외 추천 후보 유니버스 정의와 호라이즌별 스크리닝 로직."""

from typing import Any

from app.db.supabase_client import Repository
from app.services.technical_analysis_service import TechnicalAnalysisResult
from app.utils.logging import log_external_failure
from app.utils.tickers import normalize_ticker

MAX_RECOMMENDED_CANDIDATES = 10
CANDIDATE_HORIZON_RULES = {
    "short": {"min_score": 68, "label": "단기 5거래일", "target_days": 5},
    "medium": {"min_score": 64, "label": "중기 20거래일", "target_days": 20},
    "long": {"min_score": 60, "label": "장기 60거래일", "target_days": 60},
}
CANDIDATE_UNIVERSE: dict[str, list[dict[str, str]]] = {
    "domestic": [
        {"market": "KR", "ticker": "005930", "name": "삼성전자", "currency": "KRW"},
        {"market": "KR", "ticker": "000660", "name": "SK하이닉스", "currency": "KRW"},
        {"market": "KR", "ticker": "005380", "name": "현대차", "currency": "KRW"},
        {"market": "KR", "ticker": "000270", "name": "Kia", "currency": "KRW"},
        {"market": "KR", "ticker": "035420", "name": "NAVER", "currency": "KRW"},
        {"market": "KR", "ticker": "035720", "name": "Kakao", "currency": "KRW"},
        {"market": "KR", "ticker": "068270", "name": "셀트리온", "currency": "KRW"},
        {"market": "KR", "ticker": "105560", "name": "KB금융", "currency": "KRW"},
        {"market": "KR", "ticker": "055550", "name": "Shinhan Financial", "currency": "KRW"},
        {"market": "KR", "ticker": "006400", "name": "Samsung SDI", "currency": "KRW"},
        {"market": "KR", "ticker": "051910", "name": "LG Chem", "currency": "KRW"},
        {"market": "KR", "ticker": "012450", "name": "Hanwha Aerospace", "currency": "KRW"},
        {"market": "KR", "ticker": "064350", "name": "Hyundai Rotem", "currency": "KRW"},
        {"market": "KR", "ticker": "034020", "name": "Doosan Enerbility", "currency": "KRW"},
        {"market": "KR", "ticker": "069500", "name": "KODEX 200", "currency": "KRW"},
        {"market": "KR", "ticker": "091160", "name": "KODEX 반도체", "currency": "KRW"},
        {"market": "KR", "ticker": "305720", "name": "KODEX Battery", "currency": "KRW"},
        {"market": "KR", "ticker": "360750", "name": "TIGER US S&P500", "currency": "KRW"},
        {"market": "KR", "ticker": "133690", "name": "TIGER NASDAQ100", "currency": "KRW"},
    ],
    "global": [
        {"market": "US", "ticker": "NVDA", "name": "NVIDIA", "currency": "USD"},
        {"market": "US", "ticker": "MSFT", "name": "Microsoft", "currency": "USD"},
        {"market": "US", "ticker": "AAPL", "name": "Apple", "currency": "USD"},
        {"market": "US", "ticker": "AMZN", "name": "Amazon", "currency": "USD"},
        {"market": "US", "ticker": "GOOGL", "name": "Alphabet", "currency": "USD"},
        {"market": "US", "ticker": "META", "name": "Meta Platforms", "currency": "USD"},
        {"market": "US", "ticker": "TSLA", "name": "Tesla", "currency": "USD"},
        {"market": "US", "ticker": "AVGO", "name": "Broadcom", "currency": "USD"},
        {"market": "US", "ticker": "AMD", "name": "AMD", "currency": "USD"},
        {"market": "US", "ticker": "NFLX", "name": "Netflix", "currency": "USD"},
        {"market": "US", "ticker": "COST", "name": "Costco", "currency": "USD"},
        {"market": "US", "ticker": "JPM", "name": "JPMorgan Chase", "currency": "USD"},
        {"market": "US", "ticker": "LLY", "name": "Eli Lilly", "currency": "USD"},
        {"market": "US", "ticker": "V", "name": "Visa", "currency": "USD"},
        {"market": "US", "ticker": "BRK.B", "name": "Berkshire Hathaway", "currency": "USD"},
        {"market": "ETF", "ticker": "VOO", "name": "Vanguard S&P 500 ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "SPY", "name": "SPDR S&P 500 ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "QQQ", "name": "Invesco QQQ Trust", "currency": "USD"},
        {"market": "ETF", "ticker": "SMH", "name": "VanEck Semiconductor ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "SCHD", "name": "Schwab US Dividend ETF", "currency": "USD"},
        {
            "market": "ETF",
            "ticker": "VTI",
            "name": "Vanguard Total Stock Market ETF",
            "currency": "USD",
        },
        {"market": "ETF", "ticker": "IWM", "name": "iShares Russell 2000 ETF", "currency": "USD"},
        {
            "market": "ETF",
            "ticker": "XLK",
            "name": "Technology Select Sector SPDR",
            "currency": "USD",
        },
        {"market": "ETF", "ticker": "GLD", "name": "SPDR Gold Shares", "currency": "USD"},
        {
            "market": "ETF",
            "ticker": "TLT",
            "name": "iShares 20+ Year Treasury Bond ETF",
            "currency": "USD",
        },
    ],
}


def horizon_rule(candidate_horizon: str) -> dict[str, Any]:
    return CANDIDATE_HORIZON_RULES.get(candidate_horizon, CANDIDATE_HORIZON_RULES["medium"])


def candidate_horizon_score(
    technical_analysis: TechnicalAnalysisResult,
    candidate_horizon: str,
) -> float:
    score = float(technical_analysis.technical_score)
    breakdown = technical_analysis.score_breakdown
    indicators = technical_analysis.indicators
    rsi = float(indicators.get("rsi_14") or 0)
    volume_rate = float(indicators.get("volume_change_rate") or 0)

    if candidate_horizon == "short":
        score += (breakdown.get("momentum", 0) * 0.5) + (breakdown.get("volume", 0) * 0.7)
        if 55 <= rsi <= 72:
            score += 5
        if volume_rate > 20:
            score += 3
        return score
    if candidate_horizon == "long":
        score += (breakdown.get("trend", 0) * 0.7) + (breakdown.get("volatility", 0) * 0.4)
        if rsi <= 75:
            score += 3
        return score
    score += (breakdown.get("trend", 0) * 0.4) + (breakdown.get("price_position", 0) * 0.4)
    if 50 <= rsi <= 70:
        score += 3
    return score


def candidate_assets(repository: Repository, report_type: str) -> list[dict[str, Any]]:
    """사용자 구성 후보(candidate_assets)를 우선하고, 없으면 기본 유니버스를 사용한다."""
    market_filter = {"KR"} if report_type == "domestic" else {"US", "ETF"}
    try:
        candidate_rows = repository.list_candidate_assets()
    except Exception as exc:
        log_external_failure(
            "candidate_assets",
            exc,
            {"operation": "list_candidate_assets_for_report"},
        )
        candidate_rows = []
    configured_candidates = [
        row
        for row in candidate_rows
        if row.get("is_active", True) and row.get("market") in market_filter
    ]
    if configured_candidates:
        return [
            {
                "id": None,
                "market": candidate["market"],
                "ticker": candidate["ticker"],
                "name": candidate["name"],
                "currency": candidate.get("currency") or "KRW",
                "quantity": 0,
                "avg_price": 0,
                "memo": candidate.get("memo") or "보유 외 추천 후보",
            }
            for candidate in configured_candidates
        ]
    return [
        {
            **candidate,
            "id": None,
            "quantity": 0,
            "avg_price": 0,
            "memo": "보유 외 추천 후보",
        }
        for candidate in CANDIDATE_UNIVERSE.get(report_type, [])
    ]


def screen_candidate_rows(
    analysis_rows: list[dict[str, Any]],
    owned_tickers: set[str],
    candidate_horizon: str,
) -> list[dict[str, Any]]:
    """분석된 후보 행에서 호라이즌 점수 기준을 통과한 추천 후보만 남긴다."""
    rule = horizon_rule(candidate_horizon)
    rows = []
    for row in analysis_rows:
        asset = row["asset"]
        market_data = row["market_data"]
        technical_analysis = row["technical_analysis"]
        strategy = row["strategy"]
        if normalize_ticker(asset["ticker"]) in owned_tickers:
            continue
        if market_data.is_stale:
            continue
        if technical_analysis.technical_score < rule["min_score"]:
            continue
        horizon_score = candidate_horizon_score(technical_analysis, candidate_horizon)
        if horizon_score < rule["min_score"]:
            continue
        if strategy.action not in {"BUY", "HOLD"} or strategy.reasoning == "data-limited":
            continue
        action_update = {}
        if strategy.action == "HOLD":
            action_update = {
                "action": "WATCH",
                "reasoning": (
                    "보유하지 않은 후보이므로 신규 매수 대기(WATCH)로 해석합니다. "
                    f"{strategy.reasoning}"
                ),
            }
        strategy = strategy.model_copy(
            update={
                **action_update,
                "reasoning": (
                    f"보유 외 추가 매수 후보({rule['label']} 목표): "
                    f"{action_update.get('reasoning', strategy.reasoning)}"
                ),
                "risk": (
                    f"신규 진입 후보입니다. 목표 기간은 {rule['label']}이며, " f"{strategy.risk}"
                ),
            }
        )
        rows.append(
            {
                "asset": asset,
                "market_data": market_data,
                "technical_analysis": technical_analysis,
                "strategy": strategy,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            candidate_horizon_score(row["technical_analysis"], candidate_horizon),
            row["strategy"].confidence,
        ),
        reverse=True,
    )[:MAX_RECOMMENDED_CANDIDATES]
