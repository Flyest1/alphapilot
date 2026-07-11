const REGIME_LABELS = {
  bull: "상승장",
  bear: "하락장",
  sideways: "횡보장",
  high_volatility: "고변동성",
};

export function metricValue(value, digits = 2, suffix = "") {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return `${Number(value).toFixed(digits)}${suffix}`;
}

export function backtestSummary(backtest) {
  const metrics = backtest?.metrics || {};
  const gross = metrics.gross || {};
  const net = metrics.net || {};
  return [
    { label: "비용 전 누적", value: metricValue(gross.cumulative_return_pct, 2, "%") },
    { label: "비용 후 누적", value: metricValue(net.cumulative_return_pct, 2, "%") },
    { label: "신호 바스켓 연환산", value: metricValue(net.annualized_return_pct, 2, "%") },
    { label: "기준선 대비", value: metricValue(metrics.excess_return_pct, 2, "%p") },
    { label: "최대 낙폭", value: metricValue(net.max_drawdown_pct, 2, "%") },
    { label: "Sharpe", value: metricValue(net.sharpe) },
    { label: "Sortino", value: metricValue(net.sortino) },
    { label: "Calmar", value: metricValue(net.calmar) },
    { label: "회복기간", value: metricValue(net.recovery_days, 0, "일") },
    { label: "기대값", value: metricValue(net.expectancy_pct, 2, "%") },
    { label: "Profit factor", value: metricValue(net.profit_factor) },
    { label: "평균 이익", value: metricValue(net.average_gain_pct, 2, "%") },
    { label: "평균 손실", value: metricValue(net.average_loss_pct, 2, "%") },
    { label: "하위 10% 평균", value: metricValue(net.bottom_10pct_average_pct, 2, "%") },
    {
      label: "연환산 turnover",
      value: metricValue(metrics.turnover?.annualized),
    },
    {
      label: "연간 추천 빈도",
      value: metricValue(metrics.recommendation_frequency?.annualized, 1, "회"),
    },
    {
      label: "최악 월",
      value: net.worst_month
        ? `${net.worst_month.period} ${metricValue(net.worst_month.return_pct, 2, "%")}`
        : "-",
    },
    {
      label: "최악 분기",
      value: net.worst_quarter
        ? `${net.worst_quarter.period} ${metricValue(net.worst_quarter.return_pct, 2, "%")}`
        : "-",
    },
  ];
}

export function baselineRows(backtest) {
  return (backtest?.baselines || []).map((row) => ({
    name: row.label || row.name,
    gross: row.metrics?.gross?.cumulative_return_pct,
    net: row.metrics?.net?.cumulative_return_pct,
    drawdown: row.metrics?.net?.max_drawdown_pct,
  }));
}

export function regimeRows(backtest) {
  return (backtest?.regime_groups || [])
    .map((row) => ({
      ...row,
      label: REGIME_LABELS[row.regime] || row.regime,
    }))
    .sort((left, right) => right.sample_count - left.sample_count);
}

export function walkForwardRows(backtest) {
  return (backtest?.walk_forward?.folds || []).map((fold) => ({
    fold: Number(fold.fold) + 1,
    trainCount: fold.train_count,
    testCount: fold.test_count,
    period: `${fold.test_start_date || "-"} ~ ${fold.test_end_date || "-"}`,
    netReturn: fold.metrics?.net?.cumulative_return_pct,
    drawdown: fold.metrics?.net?.max_drawdown_pct,
  }));
}

export function costRows(backtest) {
  const costs = backtest?.costs || {};
  return [
    ["왕복 수수료", costs.fee_pct],
    ["국내 거래세", costs.kr_tax_pct],
    ["환전 스프레드", costs.fx_spread_pct],
    ["슬리피지 추정", costs.slippage_pct],
    ["평균 총비용", costs.total_cost_pct],
  ].map(([label, value]) => ({ label, value }));
}

export function marketRows(backtest) {
  return (backtest?.market_results || []).map((row) => {
    const buyHold = (row.baselines || []).find((baseline) => baseline.name === "buy_and_hold");
    const netReturn = row.metrics?.net?.cumulative_return_pct;
    const benchmarkReturn = buyHold?.metrics?.net?.cumulative_return_pct;
    return {
      market: row.market,
      sampleCount: row.sample_count,
      netReturn,
      benchmarkReturn,
      excessReturn:
        netReturn != null && benchmarkReturn != null ? netReturn - benchmarkReturn : null,
      drawdown: row.metrics?.net?.max_drawdown_pct,
      sharpe: row.metrics?.net?.sharpe,
      foldCount: row.walk_forward?.fold_count || 0,
    };
  });
}
