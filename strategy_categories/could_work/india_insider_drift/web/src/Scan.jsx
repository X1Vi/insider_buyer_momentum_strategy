import { useEffect, useState } from "react";
import { pct } from "./util.js";
import { useMounts } from "./mounts.js";
import MlCell from "./MlCell.jsx";
import { mlDirection, mlStrength, useMomentumScores } from "./momentumScores.js";
import { usePersistentState } from "./persist.js";
import MountedCharts from "./MountedCharts.jsx";

// "Momentum scan" — the standalone `insider_momentum` output, served by the Rust
// API. Recent insider buyers (last N days) + a momentum test per stock. Mount a
// stock (☆) to add it to the list and render its chart below.
export default function Scan({ onPick }) {
  const [recent, setRecent] = usePersistentState("scan_recent", 60);
  // Cluster filter: minimum distinct insiders buying within 30 days.
  const [clusterMin, setClusterMin] = usePersistentState("scan_cluster_min", 0);
  const [mlMin, setMlMin] = usePersistentState("scan_ml_min", 0);
  const [mlDir, setMlDir] = usePersistentState("scan_ml_dir", "all");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const ml = useMomentumScores();
  const { has, toggle, list, clear } = useMounts();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr("");
    fetch(`/api/scan?recent=${recent}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API ${r.status}`);
        return r.json();
      })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setErr(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [recent]);

  const rows = (data?.rows || []).filter(
    (r) =>
      (clusterMin === 0 || (r.distinct_buyers_30d || 0) >= clusterMin) &&
      (mlDir === "all" || mlDirection(ml.scoreFor(r.symbol)) === mlDir) &&
      (mlMin === 0 || mlStrength(ml.scoreFor(r.symbol)) >= mlMin)
  );

  return (
    <div>
      <div className="controls">
        <label>
          recent buyers:{" "}
          <select value={recent} onChange={(e) => setRecent(Number(e.target.value))}>
            <option value={30}>last 1 month</option>
            <option value={60}>last 2 months</option>
            <option value={90}>last 3 months</option>
          </select>
        </label>
        <label>
          insider buyers (min):{" "}
          <select value={clusterMin} onChange={(e) => setClusterMin(Number(e.target.value))}>
            <option value={0}>any</option>
            <option value={2}>≥2 insiders / 30d</option>
            <option value={3}>≥3 insiders / 30d</option>
            <option value={5}>≥5 insiders / 30d</option>
          </select>
        </label>
        <label>
          ML signal:{" "}
          <select value={mlDir} onChange={(e) => setMlDir(e.target.value)}>
            <option value="all">long + short</option>
            <option value="long">long only</option>
            <option value="short">short only</option>
            <option value="neutral">neutral</option>
          </select>
        </label>
        <label>
          ML strength:{" "}
          <select value={mlMin} onChange={(e) => setMlMin(Number(e.target.value))}>
            <option value={0}>any</option>
            <option value={0.4}>≥40%</option>
            <option value={0.5}>≥50%</option>
          </select>
        </label>
        <span className="badge">
          {rows.length} shown · {data?.momentum_count || 0} momentum / {data?.count || 0} scanned
        </span>
        {data?.anchor && <span className="sub inline">newest signal {data.anchor}</span>}
        {loading && <span className="sub inline">scanning… (priced via Groww, cached 24h)</span>}
        {err && <span className="err">error: {err}</span>}
      </div>

      <div className="card tableScroll">
        <table>
          <thead>
            <tr>
              <th>mount</th>
              <th>Symbol</th>
              <th>last buy</th>
              <th title="distinct insiders buying within 30 days">30d cluster</th>
              <th>close</th>
              <th>1m</th>
              <th>3m</th>
              <th>12m</th>
              <th>from 52w</th>
              <th>RSI</th>
              <th>trend</th>
              <th>momentum</th>
              <th title="L = P(+8% in 20 sessions), S = P(-8% in 20 sessions)">ML</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td>
                  <button
                    className={`star ${has(r.symbol) ? "on" : ""}`}
                    title={has(r.symbol) ? "unmount" : "mount (render chart below)"}
                    onClick={() => toggle(r.symbol)}
                  >
                    {has(r.symbol) ? "★" : "☆"}
                  </button>
                </td>
                <td>
                  <strong>{r.symbol}</strong>
                </td>
                <td>{r.last_buy}</td>
                <td>
                  {(r.distinct_buyers_30d || 0) >= 2 ? (
                    <span className="badge clusterBadge" title={`${r.distinct_buyers_30d} insiders / 30d · Rs${Math.round((r.cluster_value_inr || 0) / 1e5)}L`}>
                      {r.distinct_buyers_30d}/30d
                    </span>
                  ) : (
                    <span className="sub">{r.distinct_buyers_30d || 0}</span>
                  )}
                </td>
                <td>{r.close != null ? Number(r.close).toFixed(1) : "—"}</td>
                <td>{pct(r.ret1m)}</td>
                <td className={r.ret3m >= 0 ? "positive" : ""}>{pct(r.ret3m)}</td>
                <td>{pct(r.ret12m)}</td>
                <td>{pct(r.dist52w)}</td>
                <td>{r.rsi != null ? Number(r.rsi).toFixed(0) : "—"}</td>
                <td>{r.trend_ok ? "EMA ✓" : "no"}</td>
                <td>{r.momentum ? "YES" : ""}</td>
                <MlCell entry={ml.scoreFor(r.symbol)} />
                <td>
                  <button onClick={() => onPick?.(r.symbol)}>chart</button>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={14} className="sub">
                  No recent buyers in this window.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="sub">
        This is the standalone <b>insider_momentum</b> output, served by the Rust API.
        Momentum = close &gt; EMA50 &gt; EMA200 and 3-month return &gt; 0. Click ☆ to
        <b> mount</b> a stock; its chart renders below (fetched per symbol).
        {ml.data?.oos_auc != null && (
          <> ML is a separate long/short panel model. Up: +8% in 20 sessions (OOS daily AUC {ml.data.oos_cs_auc_up ?? ml.data.oos_cs_auc});
          down: -8% (OOS daily AUC {ml.data.oos_cs_auc_down ?? "n/a"}). It is a research filter, not a trade signal;
          short scores are informational because overnight cash shorting needs futures or a hedge.</>
        )}
        {ml.error && <span className="err"> ML scores unavailable: {ml.error}</span>}
      </div>

      <h2 style={{ fontSize: 15, marginTop: 18, display: "flex", alignItems: "center", gap: 12 }}>
        Mounted — {list.length}
        {list.length > 0 && (
          <button onClick={clear} title="unmount all">clear</button>
        )}
      </h2>
      <MountedCharts symbols={list} />
    </div>
  );
}
