"""리포트 생성 서비스 패키지.

- pipeline: 단계 오케스트레이션 (ReportService)
- candidate_screener: 후보 유니버스/호라이즌 스코어링
- prompt_builder: LLM 프롬프트와 컨텍스트 조립
- persistence: 리포트/전략/사이클/스냅샷 저장
- tracking: 성과 로그·추천 사이클 백필
"""

from app.services.report.candidate_screener import (
    CANDIDATE_HORIZON_RULES,
    MAX_RECOMMENDED_CANDIDATES,
)
from app.services.report.persistence import RECOMMENDATION_PRICE_CHANGE_THRESHOLD
from app.services.report.pipeline import ReportService
from app.services.report.prompt_builder import DISCLAIMER

__all__ = [
    "CANDIDATE_HORIZON_RULES",
    "DISCLAIMER",
    "MAX_RECOMMENDED_CANDIDATES",
    "RECOMMENDATION_PRICE_CHANGE_THRESHOLD",
    "ReportService",
]
