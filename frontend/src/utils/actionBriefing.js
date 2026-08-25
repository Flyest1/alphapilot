import { ACTION_LABELS, normalizeTicker } from "../api/reports.js";
import {
  compareStrategyBaseConfidence,
  downsideCalibration,
  strategyBaseConfidence,
} from "./strategyScores.js";

const RECENT_CLOSE_DAYS = 7;
const MAX_ITEMS_PER_KIND = 3;

function isRecent(timestamp, now) {
  if (!timestamp) return false;
  const parsed = new Date(timestamp).getTime();
  if (Number.isNaN(parsed)) return false;
  return now - parsed <= RECENT_CLOSE_DAYS * 24 * 60 * 60 * 1000;
}

function shortDate(timestamp) {
  const text = String(timestamp || "");
  return text.length >= 10 ? text.slice(5, 10) : "";
}

function displayAssetLabel(ticker, assetsByTicker) {
  const asset = assetsByTicker.get(normalizeTicker(ticker));
  const isDomesticAsset = asset?.market === "KR" || asset?.currency === "KRW";
  if (isDomesticAsset && asset.name?.trim()) {
    return asset.name.trim();
  }
  return ticker;
}

// 대시보드 "오늘 확인할 것" 항목을 기존 데이터에서 도출한다 (Phase 6-1).
// kind: target | stop | reduce | drift | candidate | stale
export function buildActionBriefing({
  summary,
  report,
  cycles = [],
  assets = [],
  now = Date.now(),
}) {
  const items = [];
  const assetsByTicker = new Map(assets.map((asset) => [normalizeTicker(asset.ticker), asset]));
  const ownedTickers = new Set(assetsByTicker.keys());
  const strategies = report?.content?.asset_strategies || [];

  // 1) 최근 종료된 추천 cycle: 목표/손절 도달
  const recentClosed = cycles
    .filter(
      (cycle) =>
        ["hit_target", "hit_stop"].includes(cycle.status) && isRecent(cycle.closed_at, now),
    )
    .sort((a, b) => String(b.closed_at).localeCompare(String(a.closed_at)));
  recentClosed.slice(0, MAX_ITEMS_PER_KIND).forEach((cycle) => {
    const when = shortDate(cycle.closed_at);
    const assetLabel = displayAssetLabel(cycle.ticker, assetsByTicker);
    if (cycle.status === "hit_target") {
      items.push({
        kind: "target",
        tone: "positive",
        key: `target-${cycle.id}`,
        text: `${assetLabel} 목표가 도달 (${when}) — 이익 실현 또는 전략 재검토를 확인하세요.`,
      });
    } else {
      items.push({
        kind: "stop",
        tone: "negative",
        key: `stop-${cycle.id}`,
        text: `${assetLabel} 손절가 도달 (${when}) — 손절 실행 여부와 무효화 조건을 확인하세요.`,
      });
    }
  });

  // 2) 보유 자산의 축소/매도 판단 (매도·축소 조건 체크리스트)
  strategies
    .filter(
      (strategy) =>
        ["REDUCE", "SELL"].includes(strategy.action) &&
        ownedTickers.has(normalizeTicker(strategy.ticker)),
    )
    .slice(0, MAX_ITEMS_PER_KIND)
    .forEach((strategy) => {
      const assetLabel = displayAssetLabel(strategy.ticker, assetsByTicker);
      items.push({
        kind: "reduce",
        tone: "negative",
        key: `reduce-${strategy.ticker}`,
        text:
          `보유 ${assetLabel}: ${ACTION_LABELS[strategy.action] || strategy.action} 판단 — ` +
          "매도/축소 조건과 손절 기준을 확인하세요.",
      });
    });

  // 3) 리밸런스 드리프트·집중도 경고
  (summary?.rebalance_suggestions || []).slice(0, MAX_ITEMS_PER_KIND).forEach((text, index) => {
    items.push({ kind: "drift", tone: "warning", key: `drift-${index}`, text });
  });
  (summary?.concentration_warnings || []).slice(0, MAX_ITEMS_PER_KIND).forEach((text, index) => {
    items.push({ kind: "drift", tone: "warning", key: `concentration-${index}`, text });
  });

  // 4) 신규 매수 후보 (보정 전 기술 신호 상위)
  strategies
    .filter(
      (strategy) =>
        strategy.action === "BUY" && !ownedTickers.has(normalizeTicker(strategy.ticker)),
    )
    .sort(compareStrategyBaseConfidence)
    .slice(0, MAX_ITEMS_PER_KIND)
    .forEach((strategy) => {
      const warning = downsideCalibration(strategy);
      const warningText = warning ? ` · 과거 성과 경고 ×${warning.factor}` : "";
      items.push({
        kind: "candidate",
        tone: "positive",
        key: `candidate-${strategy.ticker}`,
        text: `신규 매수 후보 ${strategy.ticker} (보정 전 점수 ${strategyBaseConfidence(strategy) ?? "-"}/100${warningText}) — 검토용 투입 금액 상한을 확인하세요.`,
      });
    });

  // 5) 데이터 지연 종목
  const staleTickers = Object.entries(report?.report_inputs?.tickers || {})
    .filter(([, inputs]) => inputs?.is_stale)
    .map(([ticker]) => displayAssetLabel(ticker, assetsByTicker));
  if (staleTickers.length) {
    items.push({
      kind: "stale",
      tone: "warning",
      key: "stale",
      text: `데이터 지연 종목: ${staleTickers.join(", ")} — 최신 시세 확인 전에는 판단을 보류하세요.`,
    });
  }

  return items;
}
