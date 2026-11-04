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


def is_kr_listing_code(ticker: str) -> bool:
    """True for KRX listing codes such as 069500, 0080G0 or 069500.KS.

    KRX codes are six characters starting with a digit; US tickers never are.
    """
    upper = str(ticker).strip().upper()
    if upper.endswith((".KS", ".KQ")):
        return True
    return len(upper) == 6 and upper.isalnum() and upper[0].isdigit()


def is_kr_listed_etf(market: str, ticker: str) -> bool:
    """An ETF row whose ticker is a KRX listing code is priced in KRW via pykrx."""
    return str(market or "").upper() == "ETF" and is_kr_listing_code(ticker)
