import { useEffect, useMemo, useState } from "react";
import { inr, pct } from "./util.js";
import Star from "./Star.jsx";
import { useBookmarks } from "./bookmarks.js";
import { usePersistentState } from "./persist.js";

const STATUS_LABEL = {
  ready: "READY",
  "near-breakout": "near breakout",
  "waiting-rise": "waiting for +10%",
  "below-trend": "below EMA trend",
  "trend-building": "trend building",
};

// Insider-armed strategy state. Rust joins each qualifying public disclosure to
// prices and computes the live momentum conditions; this component only renders.
export default function Momentum({ onPick }) {
  const [all, setAll] = usePersistentState("momentum_all", false);
  const [recent, setRecent] = usePersistentState("momentum_recent", 30); // days since newest signal: 30 | 60 | 90 | 0
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = usePersistentState("momentum_filter", "");
  // Cluster filter: minimum distinct insiders buying within the trailing 30 days.
  const [clusterMin, setClusterMin] = usePersistentState("momentum_cluster_min", 0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr("");
    fetch(`/api/momentum?all=${all}&recent=${recent}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API ${r.status}`);
        return r.json();
      })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setErr(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [all, recent]);

  const rows = useMemo(() => {
    let values = data?.rows || [];
    if (clusterMin > 0) {
      values = values.filter((r) => (r.distinct_buyers_30d || 0) >= clusterMin);
    }
    if (!filter) return values;
    const q = filter.toLowerCase();
    return values.filter((r) => r.symbol.toLowerCase().includes(q)
      || r.buyer.toLowerCase().includes(q)
      || (r.buyer_names_30d || []).some((name) => name.toLowerCase().includes(q)));
  }, [data, filter, clusterMin]);

  return (
    <div>
      <div className="controls">
        <label>
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />{" "}
          all qualifying symbols (slower)
        </label>
        <label>
          recent buyer:{" "}
          <select value={recent} onChange={(e) => setRecent(Number(e.target.value))}>
            <option value={30}>last 1 month</option>
            <option value={60}>last 2 months</option>
            <option value={90}>last 3 months</option>
            <option value={0}>any time</option>
          </select>
        </label>
        <label>
          cluster buying (1 month):{" "}
          <select value={clusterMin} onChange={(e) => setClusterMin(Number(e.target.value))}>
            <option value={0}>any</option>
            <option value={2}>≥2 insiders / 30d</option>
            <option value={3}>≥3 insiders / 30d</option>
            <option value={5}>≥5 insiders / 30d</option>
          </select>
        </label>
        <input className="filterInput" placeholder="filter symbol or buyer…"
          value={filter} onChange={(e) => setFilter(e.target.value)} />
        <span className="badge">{rows.length} shown · {data?.ready_count || 0} ready / {data?.count || 0} armed</span>
        {data?.latest_disclosure_date && (
          <span className="sub inline">
            newest signal {data.latest_disclosure_date}
            {recent ? ` · within ${recent}d of it` : ""}
          </span>
        )}
        {loading && <span className="sub inline">loading price histories…</span>}
        {err && <span className="err">error: {err}</span>}
      </div>

      <div className="card tableScroll">
        <table>
          <thead>
            <tr>
              <th>Status</th><th>Symbol</th><th>Disclosure</th><th>Buyer</th>
              <th>30d buyers</th><th>30d purchases</th><th>Buy / 20d value</th>
              <th>Rise</th><th>52w high</th><th>Trend</th><th>Score*</th><th>★</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td><span className={`status status-${r.status}`}>{STATUS_LABEL[r.status] || r.status}</span></td>
                <td><strong>{r.symbol}</strong></td>
                <td>{r.disclosure_date}</td>
                <td className="buyerCell">
                  <details>
                    <summary title={`${r.buyer} (${r.role})`}>{r.buyer}</summary>
                    <div className="buyerDetails">
                      {(r.cluster_buyers || []).map((buyer, index) => (
                        <div key={`${buyer.name}-${buyer.disclosure_date}-${index}`}>
                          <strong>{buyer.name}</strong> · {buyer.role}<br />
                          {buyer.disclosure_date} · {inr(buyer.value_inr)} · {Number(buyer.quantity || 0).toLocaleString("en-IN")} shares
                        </div>
                      ))}
                    </div>
                  </details>
                </td>
                <td>{r.distinct_buyers_30d}</td>
                <td>{inr(r.cluster_value_inr)}</td>
                <td>{r.purchase_to_median_traded_value_20d == null ? "—" : `${r.purchase_to_median_traded_value_20d.toFixed(2)}×`}</td>
                <td className={r.rise_from_disclosure >= 0.1 ? "positive" : ""}>{pct(r.rise_from_disclosure)}</td>
                <td>{pct(r.dist52w)}</td>
                <td title={`price source: ${r.price_source}`}>{r.trend_ok ? "EMA ✓" : "no"}</td>
                <td>{r.osint_score_partial}/2</td>
                <td><Star symbol={r.symbol} /></td>
                <td><button onClick={() => onPick?.(r.symbol)}>chart</button></td>
              </tr>
            ))}
            {!loading && rows.length === 0 && <tr><td colSpan={13} className="sub">No armed watches.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="sub">
        Expand a buyer name to see every person in that stock’s 30-day cluster, exact disclosure, quantity, and value.
        Prices are requested only for these buyer-triggered stocks and cached for 24 hours.
        READY means +10%, true 52-week-high breakout, and close &gt; EMA50 &gt; EMA200. Read-only; no order is placed.
      </div>
    </div>
  );
}
