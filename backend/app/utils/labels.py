"""액션/추세/리포트 타입 한국어 라벨 단일화 모듈."""

ACTION_LABELS = {
    "BUY": "매수",
    "HOLD": "보유",
    "REDUCE": "축소",
    "SELL": "매도",
    "WATCH": "관찰",
}

TREND_LABELS = {
    "strong bullish setup": "강한 상승 흐름",
    "bullish but needs confirmation": "상승 우위이나 확인 필요",
    "neutral / watch": "중립 또는 관찰",
    "weak / reduce risk": "약세, 위험 축소 필요",
    "bearish / sell or avoid": "약세, 매도 또는 회피",
    "data-limited": "데이터 제한",
}

RISK_PROFILE_LABELS = {
    "conservative": "보수적",
    "balanced": "균형",
    "aggressive": "공격적",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def trend_label(label: str) -> str:
    return TREND_LABELS.get(label, label)


def risk_profile_label(risk_profile: str) -> str:
    return RISK_PROFILE_LABELS.get(risk_profile, risk_profile)


def report_type_label(report_type: str) -> str:
    return "국내" if report_type == "domestic" else "글로벌"
