import { useEffect, useState } from "react";

import { api, readApiCache } from "../api/client.js";

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
    rules: ["예: KRW, USD", "시장 데이터 조회 없음", "전략 리포트 대상에서는 제외"],
    currency: "KRW",
  },
};

function validateAsset(payload) {
  if (!payload.ticker) return "티커를 입력하세요.";
  if (!payload.name) return "자산 이름을 입력하세요.";
  if (!Number.isFinite(payload.quantity) || payload.quantity < 0) {
    return "수량은 0 이상 숫자로 입력하세요.";
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
  const [assets, setAssets] = useState(cachedAssets);
  const [form, setForm] = useState(blankAsset);
  const [editingId, setEditingId] = useState(null);
  const [isLoading, setIsLoading] = useState(cachedAssets.length === 0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

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

  useEffect(() => {
    loadAssets({ background: cachedAssets.length > 0 });
  }, []);

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

  function startEdit(asset) {
    setError("");
    setStatus("");
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

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>자산</h1>
          <p>포트폴리오와 전략 리포트에 사용할 보유 자산을 등록합니다.</p>
        </div>
      </header>
      {error && <p className="alert">{error}</p>}
      {status && <p className="notice">{status}</p>}
      {isRefreshing && <p className="field-hint">최신 자산 정보를 확인하는 중입니다.</p>}

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
            <input value={form.name} onChange={(event) => updateField("name", event.target.value)} />
          </label>
          <label>
            수량
            <input
              min="0"
              step="0.0001"
              type="number"
              value={form.quantity}
              onChange={(event) => updateField("quantity", event.target.value)}
            />
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
            <input value={form.memo} onChange={(event) => updateField("memo", event.target.value)} />
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
        {!isLoading && assets.length === 0 && <p className="empty-state">등록된 자산이 없습니다.</p>}
        <div className="asset-card-list">
          {assets.map((asset) => (
            <article className="asset-card" key={asset.id}>
              <div className="asset-card-header">
                <div>
                  <strong>{asset.ticker}</strong>
                  <span>{asset.name}</span>
                </div>
                <span className="market-pill">{asset.market}</span>
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
                <th>티커</th>
                <th>이름</th>
                <th>수량</th>
                <th>평균 매입가</th>
                <th>통화</th>
                <th>메모</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id}>
                  <td>{asset.market}</td>
                  <td>{asset.ticker}</td>
                  <td>{asset.name}</td>
                  <td>{asset.quantity}</td>
                  <td>{asset.avg_price}</td>
                  <td>{asset.currency}</td>
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
