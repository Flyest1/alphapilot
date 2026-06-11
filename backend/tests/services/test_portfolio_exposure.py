"""Phase 4-3: 통화/시장/섹터 노출 비중과 집중도 경고."""

from app.db.supabase_client import InMemoryRepository
from app.services.portfolio_service import PortfolioService


def seed_assets(repo):
    repo.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 10,
            "avg_price": 70000,
            "currency": "KRW",
            "sector": "Technology",
        }
    )
    repo.create_asset(
        {
            "market": "US",
            "ticker": "JPM",
            "name": "JPMorgan",
            "quantity": 1,
            "avg_price": 100,
            "currency": "USD",
            "sector": "Financial Services",
        }
    )
    repo.create_asset(
        {
            "market": "CASH",
            "ticker": "KRW",
            "name": "현금",
            "quantity": 1,
            "avg_price": 100000,
            "currency": "KRW",
        }
    )


def test_summary_includes_currency_market_sector_exposure():
    repo = InMemoryRepository()
    repo.upsert_settings({"usd_krw_rate": 1000})
    seed_assets(repo)

    summary = PortfolioService(repo).get_summary()

    currency = {row["key"]: row for row in summary.currency_exposure}
    market = {row["key"]: row for row in summary.market_exposure}
    sector = {row["key"]: row for row in summary.sector_exposure}

    # 시세 조회가 없으므로 평균단가 기준: 삼성 700,000 + JPM 100,000 + 현금 100,000
    assert currency["KRW"]["value"] == 800000
    assert currency["USD"]["value"] == 100000
    assert market["KR"]["label"] == "국내"
    assert market["CASH"]["label"] == "현금"
    assert sector["Technology"]["value"] == 700000
    assert sector["현금"]["value"] == 100000
    assert round(sum(row["weight"] for row in summary.market_exposure)) == 100


def test_concentration_warnings_for_single_asset_and_sector():
    repo = InMemoryRepository()
    repo.upsert_settings({"usd_krw_rate": 1000})
    seed_assets(repo)

    summary = PortfolioService(repo).get_summary()

    # 삼성전자 비중 77.8% → 단일 종목 25% 초과 + Technology 섹터 40% 초과
    assert any("005930" in warning for warning in summary.concentration_warnings)
    assert any("Technology" in warning for warning in summary.concentration_warnings)
    # JPM(11.1%)은 경고 대상이 아니다
    assert not any("JPM" in warning for warning in summary.concentration_warnings)


def test_no_warnings_for_diversified_portfolio():
    repo = InMemoryRepository()
    repo.upsert_settings({"usd_krw_rate": 1000})
    for index in range(5):
        repo.create_asset(
            {
                "market": "KR",
                "ticker": f"00000{index}",
                "name": f"종목{index}",
                "quantity": 1,
                "avg_price": 100000,
                "currency": "KRW",
                "sector": f"섹터{index}",
            }
        )

    summary = PortfolioService(repo).get_summary()

    assert summary.concentration_warnings == []
