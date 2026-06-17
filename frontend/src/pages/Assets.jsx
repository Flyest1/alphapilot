import { useEffect, useRef, useState } from "react";

import { api, readApiCache } from "../api/client.js";
import { assetsToCsv, parseAssetsCsv } from "../utils/assetsCsv.js";

const blankAsset = {
  market: "KR",
  ticker: "",
  name: "",
  quantity: 0,
  avg_price: 0,
  currency: "KRW",
  memo: "",
};

const marketGuides = {
  KR: {
    title: "국내 주식 / 국내 ETF",
    ticker: "한국거래소 6자리 종목코드",
    placeholder: "005930, 069500 또는 0183J0",
    examples: "국내 주식과 국내 ETF는 KR을 선택하고 6자리 종목코드를 입력하세요.",
    rules: [
      "6자리 숫자 또는 영문 포함 코드 입력",
      "삼성전자: 005930",
      "TIGER 미국우주테크: 0183J0",
    ],
    currency: "KRW",
  },
  US: {
    title: "미국 개별 주식",
    ticker: "미국 주식 티커",
    placeholder: "AAPL 또는 MSFT",
    examples: "미국 개별 주식은 US를 선택하고 영문 티커를 입력하세요.",
    rules: ["영문 티커 입력", "애플: AAPL", "마이크로소프트: MSFT"],
    currency: "USD",
  },
  ETF: {
    title: "미국 상장 ETF",
    ticker: "미국 ETF 티커",
    placeholder: "VOO, SPY, QQQ 또는 SCHD",
    examples: "미국 상장 ETF는 ETF를 선택하세요. 국내 ETF는 KR을 사용합니다.",
    rules: ["미국 ETF만 선택", "VOO, SPY, QQQ, SCHD", "국내 ETF는 KR + 6자리 코드"],
    currency: "USD",
  },
  CASH: {
    title: "현금성 자산",
    ticker: "현금 구분명",
    placeholder: "KRW 또는 USD",
    examples: "현금은 자산 비중 계산에는 포함되지만 시장 데이터 조회는 건너뜁니다.",
    rules: [
      "예: KRW, USD",
      "권장 입력: 수량 1, 평균 매입가에 현금 총액 입력",
      "USD 현금은 설정의 USD-KRW 환율로 KRW 환산",
      "전략 리포트 대상에서는 제외",
    ],
    currency: "KRW",
  },
};

function validateAsset(payload) {
  if (!payload.ticker) return "티커를 입력하세요.";
  if (!payload.name) return "자산 이름을 입력하세요.";
  if (!Number.isFinite(payload.quantity) || payload.quantity < 0) {
    return "수량은 0 이상 숫자로 입력하세요.";
  }
  if (payload.market === "CASH" && payload.quantity <= 0) {
    return "현금은 수량을 1 이상으로 입력하세요. 총액을 평균 매입가에 넣는 경우 수량은 1입니다.";
  }
  if (!Number.isFinite(payload.avg_price) || payload.avg_price < 0) {
    return "평균 매입가는 0 이상 숫자로 입력하세요.";
  }
  if (payload.market === "KR" && !/^[A-Z0-9]{6}$/.test(payload.ticker)) {
    return "KR과 국내 ETF는 6자리 종목코드를 입력하세요. 예: 005930, 069500, 0183J0";
  }
  if (payload.market === "ETF" && /^[A-Z0-9]{6}$/.test(payload.ticker)) {
    return "국내 ETF 6자리 코드는 시장을 ETF가 아니라 KR로 선택하세요.";
  }
  if (["US", "ETF"].includes(payload.market) && !/^[A-Z][A-Z0-9.-]{0,14}$/.test(payload.ticker)) {
    return "미국 주식/ETF는 영문 티커를 입력하세요. 예: AAPL, VOO";
  }
  return "";
}

export default function Assets() {
  const cachedAssets = readApiCache("/api/assets") || [];
  const hasInitialCachedAssets = useRef(cachedAssets.length > 0);
  const [assets, setAssets] = useState(cachedAssets);
  const [tossStatus, setTossStatus] = useState(null);
  const [tossSyncResult, setTossSyncResult] = useState(null);
  const [form, setForm] = useState(blankAsset);
  const [editingId, setEditingId] = useState(null);
  const [isLoading, setIsLoading] = useState(cachedAssets.length === 0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSyncingToss, setIsSyncingToss] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [isImporting, setIsImporting] = useState(false);
  const fileInputRef = useRef(null);

  const guide = marketGuides[form.market] || marketGuides.KR;

  function loadAssets({ background = false } = {}) {
    if (background) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    api.assets
      .list()
      .then(setAssets)
      .catch((err) => setError(err.message))
      .finally(() => {
        setIsLoading(false);
        setIsRefreshing(false);
      });
  }

  function loadTossStatus() {
    api.toss
      .status()
      .then(setTossStatus)
      .catch(() => setTossStatus({ configured: false, mode: "read_only" }));
  }

  useEffect(() => {
    loadAssets({ background: hasInitialCachedAssets.current });
    loadTossStatus();
  }, []);

  async function syncTossHoldings() {
    setError("");
    setStatus("");
    setTossSyncResult(null);
    setIsSyncingToss(true);
    try {
      const result = await api.toss.sync();
      setTossSyncResult(result);
      setStatus(
        `Toss 보유주식 ${result.synced_count}개를 동기화했습니다. 수동 중복 ${result.duplicate_manual_assets.length}개를 확인하세요.`,
      );
      loadAssets();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSyncingToss(false);
    }
  }

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function updateMarket(value) {
    const nextGuide = marketGuides[value] || marketGuides.KR;
    setForm((current) => ({
      ...current,
      market: value,
      currency:
        !current.currency || current.currency === marketGuides[current.market]?.currency
          ? nextGuide.currency
          : current.currency,
      quantity: value === "CASH" && Number(current.quantity) === 0 ? 1 : current.quantity,
    }));
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setStatus("");
    const payload = {
      ...form,
      ticker: form.ticker.trim().toUpperCase(),
      name: form.name.trim(),
      quantity: Number(form.quantity),
      avg_price: Number(form.avg_price),
      currency: form.currency.trim().toUpperCase(),
      memo: form.memo.trim(),
    };
    const validationError = validateAsset(payload);
    if (validationError) {
      setError(validationError);
      return;
    }
    try {
      if (editingId) {
        await api.assets.update(editingId, payload);
        setStatus("자산을 저장했습니다.");
      } else {
        await api.assets.create(payload);
        setStatus("자산을 추가했습니다.");
      }
      setForm(blankAsset);
      setEditingId(null);
      loadAssets();
    } catch (err) {
      setError(err.message);
    }
  }

  async function deleteAsset(assetId) {
    setError("");
    setStatus("");
    try {
      await api.assets.remove(assetId);
      setStatus("자산을 삭제했습니다.");
      loadAssets();
    } catch (err) {
      setError(err.message);
    }
  }

  function exportCsv() {
    const csv = assetsToCsv(assets);
    const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `alphapilot-assets-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    setStatus(`${assets.length}개 자산을 CSV로 내보냈습니다.`);
  }

  async function importCsv(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError("");
    setStatus("");
    setIsImporting(true);
    try {
      const text = await file.text();
      const { assets: parsed, errors } = parseAssetsCsv(text);
      if (!parsed.length) {
        setError(errors.join(" / ") || "가져올 자산이 없습니다.");
        return;
      }
      let created = 0;
      const failures = [...errors];
      for (const payload of parsed) {
        try {
          await api.assets.create(payload);
          created += 1;
        } catch (err) {
          failures.push(`${payload.ticker}: ${err.message}`);
        }
      }
      setStatus(`CSV에서 ${created}개 자산을 추가했습니다.`);
      if (failures.length) {
        setError(`건너뛴 항목 ${failures.length}건 — ${failures.slice(0, 5).join(" / ")}`);
      }
      loadAssets();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsImporting(false);
    }
  }

  function startEdit(asset) {
    setError("");
    setStatus("");
    if (asset.source === "toss_api") {
      setError("Toss 연동 자산은 API 동기화로 갱신됩니다. 직접 수정하지 않습니다.");
      return;
    }
    setEditingId(asset.id);
    setForm({
      market: asset.market,
      ticker: asset.ticker,
      name: asset.name,
      quantity: asset.quantity,
      avg_price: asset.avg_price,
      currency: asset.currency,
      memo: asset.memo || "",
    });
  }

  function sourceLabel(asset) {
    return asset.source === "toss_api" ? "Toss 연동" : "수동";
  }

  function sourceClass(asset) {
    return asset.source === "toss_api" ? "source-pill api" : "source-pill manual";
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>자산</h1>
          <p>포트폴리오와 전략 리포트에 사용할 보유 자산을 등록합니다.</p>
        </div>
        <div className="header-actions">
          <button
            disabled={isImporting}
            type="button"
            onClick={() => fileInputRef.current?.click()}
          >
            {isImporting ? "CSV 가져오는 중" : "CSV 가져오기"}
          </button>
          <button disabled={!assets.length} type="button" onClick={exportCsv}>
            CSV 내보내기
          </button>
          <button
            disabled={!tossStatus?.configured || isSyncingToss}
            type="button"
            onClick={syncTossHoldings}
          >
            {isSyncingToss ? "Toss 동기화 중" : "Toss 보유주식 동기화"}
          </button>
          <input
            accept=".csv,text/csv"
            hidden
            ref={fileInputRef}
            type="file"
            onChange={importCsv}
          />
        </div>
      </header>
      {error && <p className="alert">{error}</p>}
      {status && <p className="notice">{status}</p>}
      {tossStatus && !tossStatus.configured && (
        <p className="alert">
          Toss API 연동을 사용하려면 백엔드 환경변수 TOSS_INVEST_CLIENT_ID,
          TOSS_INVEST_CLIENT_SECRET, TOSS_INVEST_ACCOUNT_ID를 설정하세요.
        </p>
      )}
      {isRefreshing && <p className="field-hint">최신 자산 정보를 확인하는 중입니다.</p>}

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>Toss 보유주식 연동</h2>
            <p>
              조회 전용으로 계좌 보유주식을 동기화합니다. 주문, 정정, 취소 기능은 제공하지 않습니다.
            </p>
          </div>
          <div className="inline-metrics">
            <span>{tossStatus?.configured ? "설정됨" : "미설정"}</span>
            <span>{tossStatus?.mode || "read_only"}</span>
          </div>
        </div>
        {tossSyncResult && (
          <div className="sync-result">
            <p>
              생성 {tossSyncResult.created_count}개, 갱신 {tossSyncResult.updated_count}개, 보유
              해제 반영 {tossSyncResult.stale_count}개
            </p>
            {!!tossSyncResult.duplicate_manual_assets.length && (
              <>
                <strong>중복 가능 수동 자산</strong>
                <ul>
                  {tossSyncResult.duplicate_manual_assets.map((asset) => (
                    <li key={asset.id}>
                      {asset.market} {asset.ticker} {asset.name} - 수량 {asset.quantity}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </section>

      <section className="panel">
        <form className="asset-form" onSubmit={submit}>
          <label>
            시장
            <select value={form.market} onChange={(event) => updateMarket(event.target.value)}>
              <option value="KR">KR - 국내 주식/국내 ETF</option>
              <option value="US">US - 미국 주식</option>
              <option value="ETF">ETF - 미국 ETF</option>
              <option value="CASH">CASH - 현금</option>
            </select>
          </label>
          <label>
            티커
            <input
              autoCapitalize="characters"
              inputMode="text"
              placeholder={guide.placeholder}
              value={form.ticker}
              onChange={(event) => updateField("ticker", event.target.value.toUpperCase())}
            />
            <span className="field-hint">{guide.ticker}</span>
          </label>
          <label>
            이름
            <input
              value={form.name}
              onChange={(event) => updateField("name", event.target.value)}
            />
          </label>
          <label>
            수량
            <input
              min={form.market === "CASH" ? "1" : "0"}
              step="0.0001"
              type="number"
              value={form.quantity}
              onChange={(event) => updateField("quantity", event.target.value)}
            />
            {form.market === "CASH" && (
              <span className="field-hint">
                현금 총액을 평균 매입가에 넣는 경우 수량은 1입니다.
              </span>
            )}
          </label>
          <label>
            평균 매입가
            <input
              min="0"
              step="0.0001"
              type="number"
              value={form.avg_price}
              onChange={(event) => updateField("avg_price", event.target.value)}
            />
          </label>
          <label>
            통화
            <input
              placeholder={guide.currency}
              value={form.currency}
              onChange={(event) => updateField("currency", event.target.value.toUpperCase())}
            />
          </label>
          <label className="wide">
            메모
            <input
              value={form.memo}
              onChange={(event) => updateField("memo", event.target.value)}
            />
          </label>
          <button type="submit">{editingId ? "자산 저장" : "자산 추가"}</button>
        </form>
        <div className="asset-guide">
          <div>
            <strong>{guide.title}</strong>
            <p>{guide.examples}</p>
          </div>
          <ul>
            {guide.rules.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="panel">
        {isLoading && <p className="empty-state">자산을 불러오는 중입니다.</p>}
        {!isLoading && assets.length === 0 && (
          <p className="empty-state">등록된 자산이 없습니다.</p>
        )}
        <div className="asset-card-list">
          {assets.map((asset) => (
            <article className="asset-card" key={asset.id}>
              <div className="asset-card-header">
                <div>
                  <strong>{asset.ticker}</strong>
                  <span>{asset.name}</span>
                </div>
                <div className="badge-stack">
                  <span className="market-pill">{asset.market}</span>
                  <span className={sourceClass(asset)}>{sourceLabel(asset)}</span>
                </div>
              </div>
              <dl>
                <div>
                  <dt>수량</dt>
                  <dd>{asset.quantity}</dd>
                </div>
                <div>
                  <dt>평균 매입가</dt>
                  <dd>{asset.avg_price}</dd>
                </div>
                <div>
                  <dt>통화</dt>
                  <dd>{asset.currency}</dd>
                </div>
                <div>
                  <dt>메모</dt>
                  <dd>{asset.memo || "-"}</dd>
                </div>
                <div>
                  <dt>동기화</dt>
                  <dd>
                    {asset.synced_at ? new Date(asset.synced_at).toLocaleString("ko-KR") : "-"}
                  </dd>
                </div>
              </dl>
              <div className="row-actions">
                <button type="button" onClick={() => startEdit(asset)}>
                  수정
                </button>
                <button type="button" onClick={() => deleteAsset(asset.id)}>
                  삭제
                </button>
              </div>
            </article>
          ))}
        </div>
        <div className="table-wrap asset-table">
          <table>
            <thead>
              <tr>
                <th>시장</th>
                <th>출처</th>
                <th>티커</th>
                <th>이름</th>
                <th>수량</th>
                <th>평균 매입가</th>
                <th>통화</th>
                <th>동기화</th>
                <th>메모</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id}>
                  <td>{asset.market}</td>
                  <td>
                    <span className={sourceClass(asset)}>{sourceLabel(asset)}</span>
                  </td>
                  <td>{asset.ticker}</td>
                  <td>{asset.name}</td>
                  <td>{asset.quantity}</td>
                  <td>{asset.avg_price}</td>
                  <td>{asset.currency}</td>
                  <td>
                    {asset.synced_at ? new Date(asset.synced_at).toLocaleString("ko-KR") : "-"}
                  </td>
                  <td>{asset.memo}</td>
                  <td className="row-actions">
                    <button type="button" onClick={() => startEdit(asset)}>
                      수정
                    </button>
                    <button type="button" onClick={() => deleteAsset(asset.id)}>
                      삭제
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
