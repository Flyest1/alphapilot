from app.utils.tickers import infer_market, normalize_ticker


def test_normalize_ticker_strips_kr_suffixes_and_uppercases():
    assert normalize_ticker("005930.KS") == "005930"
    assert normalize_ticker("035720.kq".upper()) == "035720"
    assert normalize_ticker(" aapl ") == "AAPL"


def test_infer_market_handles_kr_us_index_and_dotted_tickers():
    assert infer_market("005930") == "KR"
    assert infer_market("005930.KS") == "KR"
    assert infer_market("0183J0") == "KR"
    assert infer_market("AAPL") == "US"
    assert infer_market("BRK.B") == "US"
    assert infer_market("^GSPC") == "US"
