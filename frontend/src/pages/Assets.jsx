import { useEffect, useState } from "react";

import { api } from "../api/client.js";

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
    ticker: "6-digit KRX code",
    placeholder: "005930 or 069500",
    examples: "Stocks and domestic ETFs use KR with a 6-digit code.",
    currency: "KRW",
  },
  US: {
    ticker: "US stock ticker",
    placeholder: "AAPL or MSFT",
    examples: "Use US for individual US-listed stocks.",
    currency: "USD",
  },
  ETF: {
    ticker: "US ETF ticker",
    placeholder: "VOO, SPY, QQQ, or SCHD",
    examples: "Use ETF for US-listed ETFs. Domestic ETFs should use KR.",
    currency: "USD",
  },
  CASH: {
    ticker: "Cash label",
    placeholder: "KRW or USD",
    examples: "Cash is included in allocation and skips market data fetches.",
    currency: "KRW",
  },
};

export default function Assets() {
  const [assets, setAssets] = useState([]);
  const [form, setForm] = useState(blankAsset);
  const [editingId, setEditingId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const guide = marketGuides[form.market] || marketGuides.KR;

  function loadAssets() {
    setIsLoading(true);
    api.assets
      .list()
      .then(setAssets)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    loadAssets();
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
    try {
      if (editingId) {
        await api.assets.update(editingId, payload);
        setStatus("Asset saved.");
      } else {
        await api.assets.create(payload);
        setStatus("Asset added.");
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
      setStatus("Asset deleted.");
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
          <h1>Assets</h1>
          <p>Register holdings used by portfolio and strategy reports.</p>
        </div>
      </header>
      {error && <p className="alert">{error}</p>}
      {status && <p className="notice">{status}</p>}

      <section className="panel">
        <form className="asset-form" onSubmit={submit}>
          <label>
            Market
            <select value={form.market} onChange={(event) => updateMarket(event.target.value)}>
              <option value="KR">KR</option>
              <option value="US">US</option>
              <option value="ETF">ETF</option>
              <option value="CASH">CASH</option>
            </select>
          </label>
          <label>
            Ticker
            <input
              placeholder={guide.placeholder}
              value={form.ticker}
              onChange={(event) => updateField("ticker", event.target.value.toUpperCase())}
            />
            <span className="field-hint">{guide.ticker}</span>
          </label>
          <label>
            Name
            <input value={form.name} onChange={(event) => updateField("name", event.target.value)} />
          </label>
          <label>
            Quantity
            <input
              min="0"
              step="0.0001"
              type="number"
              value={form.quantity}
              onChange={(event) => updateField("quantity", event.target.value)}
            />
          </label>
          <label>
            Average price
            <input
              min="0"
              step="0.0001"
              type="number"
              value={form.avg_price}
              onChange={(event) => updateField("avg_price", event.target.value)}
            />
          </label>
          <label>
            Currency
            <input
              placeholder={guide.currency}
              value={form.currency}
              onChange={(event) => updateField("currency", event.target.value.toUpperCase())}
            />
          </label>
          <label className="wide">
            Memo
            <input value={form.memo} onChange={(event) => updateField("memo", event.target.value)} />
          </label>
          <button type="submit">{editingId ? "Save asset" : "Add asset"}</button>
        </form>
        <p className="form-hint">{guide.examples}</p>
      </section>

      <section className="panel">
        {isLoading && <p className="empty-state">Loading assets.</p>}
        {!isLoading && assets.length === 0 && <p className="empty-state">No assets registered yet.</p>}
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
                  <dt>Quantity</dt>
                  <dd>{asset.quantity}</dd>
                </div>
                <div>
                  <dt>Average price</dt>
                  <dd>{asset.avg_price}</dd>
                </div>
                <div>
                  <dt>Currency</dt>
                  <dd>{asset.currency}</dd>
                </div>
                <div>
                  <dt>Memo</dt>
                  <dd>{asset.memo || "-"}</dd>
                </div>
              </dl>
              <div className="row-actions">
                <button type="button" onClick={() => startEdit(asset)}>
                  Edit
                </button>
                <button type="button" onClick={() => deleteAsset(asset.id)}>
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
        <div className="table-wrap asset-table">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Ticker</th>
                <th>Name</th>
                <th>Quantity</th>
                <th>Average price</th>
                <th>Currency</th>
                <th>Memo</th>
                <th>Actions</th>
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
                      Edit
                    </button>
                    <button type="button" onClick={() => deleteAsset(asset.id)}>
                      Delete
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
