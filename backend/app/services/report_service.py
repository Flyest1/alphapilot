"""하위 호환 모듈: 실제 구현은 app.services.report 패키지로 이동했다."""

from app.services.report import (
    CANDIDATE_HORIZON_RULES,
    CANDIDATE_UNIVERSE,
    DISCLAIMER,
    MAX_RECOMMENDED_CANDIDATES,
    RECOMMENDATION_PRICE_CHANGE_THRESHOLD,
    ReportService,
)

__all__ = [
    "CANDIDATE_HORIZON_RULES",
    "CANDIDATE_UNIVERSE",
    "DISCLAIMER",
    "MAX_RECOMMENDED_CANDIDATES",
    "RECOMMENDATION_PRICE_CHANGE_THRESHOLD",
    "ReportService",
]
