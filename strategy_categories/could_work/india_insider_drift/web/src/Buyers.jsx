import { useEffect, useMemo, useState } from "react";
import { inr, rupees, isoFromDmY } from "./util.js";
import Star from "./Star.jsx";
import { usePersistentState } from "./persist.js";

// Largest number of DISTINCT insiders who bought within any trailing `windowDays`
// span. Uses the disclosure date (point-in-time), never the trade date.
function maxDistinctInWindow(events, windowDays) {
  const items = events
    .map((e) => ({
      t: Date.parse(isoFromDmY(e.disclosure_date) || String(e.disclosure_date || "").slice(0, 10)),
      buyer: e.buyer,
    }))
    .filter((x) => Number.isFinite(x.t))
    .sort((a, b) => a.t - b.t);
  const span = windowDays * 86_400_000;
  let best = 0;
  for (let i = 0; i < items.length; i++) {
    const lo = items[i].t - span;
    const buyers = new Set();
    for (let j = i; j >= 0 && items[j].t >= lo; j--) buyers.add(items[j].buyer);
    if (buyers.size > best) best = buyers.size;
  }
  return best;
}

// "Insider buyers" page: one row per stock, with every major insider buy under
// it. Data comes entirely from the Rust API (/api/insiders).
export default function Buyers({ onPick }) {
  const [all, setAll] = usePersistentState("buyers_all", false); // default: explicit strategy pool
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = usePersistentState("buyers_filter", "");
  // Cluster filter: minimum distinct insiders buying within a 30-day window.
  const [clusterMin, setClusterMin] = usePersistentState("buyers_cluster_min", 0);
  const [openList, setOpenList] = usePersistentState("buyers_open", []); // expanded symbols
  const open = useMemo(() => new Set(openList), [openList]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr("");
    fetch(`/api/insiders?all=${all}`)
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
  }, [all]);

  const groups = useMemo(() => {
    const evs = (data && data.events) || [];
    const map = new Map();
    for (const e of evs) {
      if (!map.has(e.symbol)) map.set(e.symbol, []);
      map.get(e.symbol).push(e);
    }
    const arr = [...map.entries()].map(([symbol, events]) => {
      events.sort((a, b) => (a.disclosure_date < b.disclosure_date ? 1 : -1));
      const total = events.reduce((s, e) => s + (e.value_inr || 0), 0);
      const cluster30 = maxDistinctInWindow(events, 30);
      return { symbol, events, total, cluster30 };
    });
    arr.sort((a, b) =>
      b.cluster30 - a.cluster30 || b.events.length - a.events.length || b.total - a.total
    );
    return arr;
  }, [data]);

  const shown = groups.filter((g) => {
    if (filter && !g.symbol.toLowerCase().includes(filter.toLowerCase())) return false;
    if (clusterMin > 0 && g.cluster30 < clusterMin) return false;
    return true;
  });

  const toggle = (s) =>
    setOpenList((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]
    );

  return (
    <div>
      <div className="controls">
        <label>
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />{" "}
          all qualifying symbols (ignore pool)
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
        <input
          placeholder="filter symbol…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ background: "#1a1f26", color: "#e6e6e6", border: "1px solid #2a313a", borderRadius: 6, padding: "7px 10px" }}
        />
        <span className="badge">
          {(data && data.count) || 0} buys / {shown.length} of {groups.length} stocks
        </span>
        {loading && <span className="sub">loading…</span>}
        {err && <span className="err">error: {err}</span>}
      </div>

      {shown.map((g) => (
        <div className="card" key={g.symbol}>
          <div
            className="rowHead"
            onClick={() => toggle(g.symbol)}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 12 }}
          >
            <strong style={{ minWidth: 120 }}>{g.symbol}</strong>
            <span className="badge">{g.events.length} buys</span>
            {g.cluster30 >= 2 && (
              <span className="badge clusterBadge" title="most distinct insiders buying within any 30-day window">
                {g.cluster30} insiders / 30d
              </span>
            )}
            <span className="sub">{inr(g.total)}</span>
            <span style={{ marginLeft: "auto" }}>{open.has(g.symbol) ? "▾" : "▸"}</span>
            <Star symbol={g.symbol} />
            <button
              onClick={(e) => {
                e.stopPropagation();
                onPick && onPick(g.symbol);
              }}
            >
              chart
            </button>
          </div>
          {open.has(g.symbol) && (
            <table style={{ marginTop: 8 }}>
              <thead>
                <tr>
                  <th>Trade date</th>
                  <th>Disclosure</th>
                  <th>Buyer</th>
                  <th>Role</th>
                  <th>Quantity</th>
                  <th>Estimated avg price</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                {g.events.map((e, i) => (
                  <tr key={i}>
                    <td>{e.trade_date}</td>
                    <td>{(e.disclosure_date || "").slice(0, 10)}</td>
                    <td>{e.buyer}</td>
                    <td>{e.role}</td>
                    <td>{Number(e.qty || 0).toLocaleString("en-IN")}</td>
                    <td>{e.estimated_price == null ? "—" : `${rupees(e.estimated_price)} (est.)`}</td>
                    <td>{inr(e.value_inr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
      {!loading && shown.length === 0 && (
        <div className="sub">No insider buys {all ? "" : "for the pool "}in the window.</div>
      )}
    </div>
  );
}
