from app.db.supabase_client import InMemoryRepository
from app.models.report import AssetStrategy
from app.services.report.persistence import ReportPersistence


def test_original_decision_survives_reused_cycle_target_updates():
    repo = InMemoryRepository()
    persistence = ReportPersistence(repo)
    cycles = []
    original = AssetStrategy(
        ticker="AAPL",
        name="Apple",
        action="BUY",
        confidence=65,
        current_price=100,
        target_price=110,
        stop_loss=90,
        reasoning="trend",
        risk="loss",
        invalidation_condition="trend breaks",
    )
    persistence.sync_recommendation_cycle(
        original,
        {"id": "first-strategy"},
        {"id": "first-report", "report_type": "global"},
        "short",
        cycles,
        technical_score=70,
    )
    first = cycles[0]["metadata"]["original_decision"].copy()
    persistence.sync_recommendation_cycle(
        original.model_copy(update={"target_price": 112, "confidence": 85}),
        {"id": "later-strategy"},
        {"id": "later-report", "report_type": "global"},
        "short",
        cycles,
        technical_score=90,
    )
    assert len(cycles) == 1
    assert cycles[0]["target_price"] == 112
    assert cycles[0]["metadata"]["original_decision"] == first
    assert first["target_price"] == 110
    assert first["confidence"] == 65
    assert first["strategy_id"] == "first-strategy"
    assert first["technical_score"] == 70
    assert first["decision_at"] == cycles[0]["started_at"]
