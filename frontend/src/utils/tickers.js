// Ticker formats accepted by asset and candidate forms (shared so both forms agree).
const KR_TICKER_PATTERN = /^[A-Z0-9]{6}$/;
const US_TICKER_PATTERN = /^[A-Z][A-Z0-9.-]{0,14}$/;

export function isKrTicker(ticker) {
  return KR_TICKER_PATTERN.test(String(ticker || ""));
}

export function isUsTicker(ticker) {
  return US_TICKER_PATTERN.test(String(ticker || ""));
}
