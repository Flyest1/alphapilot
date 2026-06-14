"""티커 정규화/시장 추론 단일화 모듈.

report/benchmark 서비스에 흩어져 있던 동일 로직을 한곳으로 모은다.
"""


def normalize_ticker(ticker: str) -> str:
    return str(ticker).upper().replace(".KS", "").replace(".KQ", "").strip()


def infer_market(ticker: str) -> str:
    upper = str(ticker).strip().upper()
    if upper.startswith("^"):
        return "US"
    clean = upper.replace(".KS", "").replace(".KQ", "")
    if "." in clean:
        return "US"
    if len(clean) == 6 and clean.isalnum():
        return "KR"
    return "US"
