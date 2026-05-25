import { useEffect, useState } from "react";

import { api } from "../api/client.js";

const blankCandidate = {
  market: "KR",
  ticker: "",
  name: "",
  currency: "KRW",
  memo: "",
  is_active: true,
};

const marketDefaults = {
  KR: { currency: "KRW", placeholder: "005930 또는 069500" },
  US: { currency: "USD", placeholder: "AAPL 또는 NVDA" },
  ETF: { currency: "USD", placeholder: "VOO 또는 QQQ" },
};

function validateCandidate(payload) {
  if (!payload.ticker) return "후보 티커를 입력하세요.";
  if (!payload.name) return "후보 이름을 입력하세요.";
  if (payload.market === "KR" && !/^\d{6}$/.test(payload.ticker)) {
    return "국내 후보는 6자리 종목코드를 입력하세요.";
  }
  if (["US", "ETF"].includes(payload.market) && !/^[A-Z][A-Z0-9.-]{0,14}$/.test(payload.ticker)) {
    return "미국 주식/ETF 후보는 영문 티커를 입력하세요.";
  }
  return "";
}

export default function CandidateAssetsPanel() {
  const [candidates, setCandidates] = useState([]);
  const [form, setForm] = useState(blankCandidate);
  const [editingId, setEditingId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function loadCandidates() {
    setIsLoading(true);
    api.candidates
      .list()
      .then(setCandidates)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    loadCandidates();
  }, []);

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function updateMarket(market) {
    const defaults = marketDefaults[market] || marketDefaults.KR;
    setForm((current) => ({
      ...current,
      market,
      currency: defaults.currency,
    }));
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    const payload = {
      ...form,
      ticker: form.ticker.trim().toUpperCase(),
      name: form.name.trim(),
      currency: form.currency.trim().toUpperCase(),
      memo: form.memo.trim(),
      is_active: Boolean(form.is_active),
    };
    const validationError = validateCandidate(payload);
    if (validationError) {
      setError(validationError);
      return;
    }
    try {
      if (editingId) {
        await api.candidates.update(editingId, payload);
        setMessage("후보 종목을 저장했습니다.");
      } else {
        await api.candidates.create(payload);
        setMessage("후보 종목을 추가했습니다.");
      }
      setForm(blankCandidate);
      setEditingId(null);
      loadCandidates();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(candidateId) {
    setError("");
    setMessage("");
    try {
      await api.candidates.remove(candidateId);
      setMessage("후보 종목을 삭제했습니다.");
      loadCandidates();
    } catch (err) {
      setError(err.message);
    }
  }

  function startEdit(candidate) {
    setError("");
    setMessage("");
    setEditingId(candidate.id);
    setForm({
      market: candidate.market,
      ticker: candidate.ticker,
      name: candidate.name,
      currency: candidate.currency,
      memo: candidate.memo || "",
      is_active: candidate.is_active,
    });
  }

  const placeholder = marketDefaults[form.market]?.placeholder || marketDefaults.KR.placeholder;

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>추가 매수 후보군</h2>
          <p>보유 외 추천을 받을 관심 후보 종목을 직접 관리합니다.</p>
        </div>
        <div className="inline-metrics">
          <span>{candidates.filter((candidate) => candidate.is_active).length}개 활성</span>
          <span>{candidates.length}개 전체</span>
        </div>
      </div>
      {error && <p className="alert">{error}</p>}
      {message && <p className="notice">{message}</p>}
      <form className="asset-form" onSubmit={submit}>
        <label>
          시장
          <select value={form.market} onChange={(event) => updateMarket(event.target.value)}>
            <option value="KR">KR - 국내 주식/국내 ETF</option>
            <option value="US">US - 미국 주식</option>
            <option value="ETF">ETF - 미국 ETF</option>
          </select>
        </label>
        <label>
          티커
          <input
            autoCapitalize="characters"
            inputMode={form.market === "KR" ? "numeric" : "text"}
            placeholder={placeholder}
            value={form.ticker}
            onChange={(event) => updateField("ticker", event.target.value.toUpperCase())}
          />
        </label>
        <label>
          이름
          <input value={form.name} onChange={(event) => updateField("name", event.target.value)} />
        </label>
        <label>
          통화
          <input
            value={form.currency}
            onChange={(event) => updateField("currency", event.target.value.toUpperCase())}
          />
        </label>
        <label className="wide">
          메모
          <input value={form.memo} onChange={(event) => updateField("memo", event.target.value)} />
        </label>
        <label className="checkbox-label">
          <input
            checked={form.is_active}
            type="checkbox"
            onChange={(event) => updateField("is_active", event.target.checked)}
          />
          활성
        </label>
        <button type="submit">{editingId ? "후보 저장" : "후보 추가"}</button>
      </form>
      <p className="form-hint">
        후보군이 비어 있으면 앱의 기본 후보군을 사용합니다. 후보군을 하나라도 추가하면 활성 후보군만
        리포트 추천에 사용합니다.
      </p>

      {isLoading && <p className="empty-state">후보군을 불러오는 중입니다.</p>}
      {!isLoading && candidates.length === 0 && (
        <p className="empty-state">직접 등록한 후보 종목이 없습니다.</p>
      )}
      <div className="asset-card-list candidate-card-list">
        {candidates.map((candidate) => (
          <article className="asset-card" key={candidate.id}>
            <div className="asset-card-header">
              <div>
                <strong>{candidate.ticker}</strong>
                <span>{candidate.name}</span>
              </div>
              <div className="badge-stack">
                <span className="market-pill">{candidate.market}</span>
                <span className={`status-pill ${candidate.is_active ? "" : "warning"}`}>
                  {candidate.is_active ? "활성" : "비활성"}
                </span>
              </div>
            </div>
            <dl>
              <div>
                <dt>통화</dt>
                <dd>{candidate.currency}</dd>
              </div>
              <div>
                <dt>메모</dt>
                <dd>{candidate.memo || "-"}</dd>
              </div>
            </dl>
            <div className="row-actions">
              <button type="button" onClick={() => startEdit(candidate)}>
                수정
              </button>
              <button type="button" onClick={() => remove(candidate.id)}>
                삭제
              </button>
            </div>
          </article>
        ))}
      </div>
      <div className="table-wrap asset-table candidate-table">
        <table>
          <thead>
            <tr>
              <th>상태</th>
              <th>시장</th>
              <th>티커</th>
              <th>이름</th>
              <th>통화</th>
              <th>메모</th>
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.id}>
                <td>{candidate.is_active ? "활성" : "비활성"}</td>
                <td>{candidate.market}</td>
                <td>{candidate.ticker}</td>
                <td>{candidate.name}</td>
                <td>{candidate.currency}</td>
                <td>{candidate.memo}</td>
                <td className="row-actions">
                  <button type="button" onClick={() => startEdit(candidate)}>
                    수정
                  </button>
                  <button type="button" onClick={() => remove(candidate.id)}>
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
