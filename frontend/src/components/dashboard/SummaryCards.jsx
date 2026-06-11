import { formatMoney } from "../../utils/formatters.js";
import SummaryCard from "../SummaryCard.jsx";

export default function SummaryCards({ summary }) {
  return (
    <>
      <div className="summary-grid">
        <SummaryCard label="총 평가금액(KRW)" value={formatMoney(summary?.total_market_value)} />
        <SummaryCard
          label="평가손익(KRW)"
          value={formatMoney(summary?.total_profit_loss)}
          tone={summary?.total_profit_loss >= 0 ? "positive" : "negative"}
        />
        <SummaryCard
          label="수익률"
          value={`${summary?.total_return_rate ?? 0}%`}
          tone={summary?.total_return_rate >= 0 ? "positive" : "negative"}
        />
        <SummaryCard label="현금(KRW)" value={formatMoney(summary?.cash_value)} />
        <SummaryCard
          label="1일 변동(KRW)"
          value={formatMoney(summary?.daily_profit_loss)}
          tone={summary?.daily_profit_loss >= 0 ? "positive" : "negative"}
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
