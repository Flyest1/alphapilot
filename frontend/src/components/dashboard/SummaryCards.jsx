import { formatMoney } from "../../utils/formatters.js";
import SummaryCard from "../SummaryCard.jsx";

const money = (value) => (value == null ? "계산 불가" : formatMoney(value));
const percent = (value) => (value == null ? "계산 불가" : `${value}%`);
const tone = (value) => (value == null ? "neutral" : value >= 0 ? "positive" : "negative");

export default function SummaryCards({ summary }) {
  return (
    <>
      {summary?.valuation_status && summary.valuation_status !== "complete" && (
        <p className="notice">
          시세 누락 또는 지연: 평가 가능 {summary.valued_asset_count}/{summary.total_asset_count}개
          · 확인된 평가액 {formatMoney(summary.valued_market_value)} KRW. 전체 평가액과 수익률은
          계산 불가합니다.
        </p>
      )}
      <div className="summary-grid">
        <SummaryCard label="총 평가금액(KRW)" value={money(summary?.total_market_value)} />
        <SummaryCard
          label="평가손익(KRW)"
          value={money(summary?.total_profit_loss)}
          tone={tone(summary?.total_profit_loss)}
        />
        <SummaryCard
          label="수익률"
          value={percent(summary?.total_return_rate)}
          tone={tone(summary?.total_return_rate)}
        />
        <SummaryCard
          label="세후·비용 차감 수익률(추정)"
          value={percent(summary?.total_net_return_rate)}
          tone={tone(summary?.total_net_return_rate)}
        />
        <SummaryCard label="현금(KRW)" value={money(summary?.cash_value)} />
        <SummaryCard
          label="1일 변동(KRW)"
          value={money(summary?.daily_profit_loss)}
          tone={tone(summary?.daily_profit_loss)}
        />
      </div>
      {summary?.usd_krw_rate && (
        <p className="field-hint">
          USD 자산은 1 USD = {formatMoney(summary.usd_krw_rate)} KRW 기준으로 환산합니다.
        </p>
      )}
    </>
  );
}
