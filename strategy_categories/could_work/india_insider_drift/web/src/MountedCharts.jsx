import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

// One mounted stock: fetch its series, draw a compact chart, and show the
// momentum RE-ARM trigger (close above EMA200, then a 52-week breakout).
function MiniChart({ symbol, range = "2y" }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setErr("");
    fetch(`/api/series?symbol=${encodeURIComponent(symbol)}&range=${range}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API ${r.status}`);
        return r.json();
      })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setErr(String(e)));
    return () => {
      cancelled = true;
    };
  }, [symbol, range]);

  const rows = data
    ? data.dates.map((date, i) => ({
        date,
        close: data.close[i],
        ema50: data.ema50[i],
        ema200: data.ema200[i],
      }))
    : [];

  // trigger logic
  const last = rows[rows.length - 1];
  const prev = rows[rows.length - 2];
  const num = (x) => (typeof x === "number" && isFinite(x) ? x : null);
  const above = last && num(last.close) > num(last.ema50) && num(last.ema50) > num(last.ema200);
  const reclaimed =
    last && prev && num(prev.close) <= num(prev.ema200) && num(last.close) > num(last.ema200);
  const hi52 = rows.length ? Math.max(...rows.slice(-252).map((r) => num(r.close) || 0)) : null;
  const breakout = last && hi52 && num(last.close) >= hi52;

  const status = breakout
    ? { label: "BREAKOUT — momentum confirmed", cls: "status-ready" }
    : above
    ? { label: "MOMENTUM (close > EMA50 > EMA200)", cls: "status-ready" }
    : reclaimed
    ? { label: "⚑ RECLAIMED EMA200 — watch", cls: "status-near-breakout" }
    : { label: "below trend — not momentum", cls: "status-below-trend" };

  return (
    <div className="card">
      <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 4, flexWrap: "wrap" }}>
        <strong>{symbol}</strong>
        {last && <span className={`status ${status.cls}`}>{status.label}</span>}
        {data?.price_source && <span className="sourceBadge">prices: {data.price_source}</span>}
        {err && <span className="err">{err}</span>}
        {!data && !err && <span className="sub inline">loading…</span>}
      </div>

      {data && last && (
        <>
          <div className="sub" style={{ marginBottom: 6 }}>
            re-arm level: close &gt; <b>{num(last.ema200)?.toFixed(1)}</b> (EMA200)
            {" · "}breakout near <b>{hi52?.toFixed(1)}</b> (52w close high)
            {" · "}last close <b>{num(last.close)?.toFixed(1)}</b>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="date" minTickGap={40} stroke="#8b97a3" />
              <YAxis domain={["auto", "auto"]} stroke="#8b97a3" width={48} />
              <Tooltip contentStyle={{ background: "#161b21", border: "1px solid #2a313a" }} />
              {hi52 && <ReferenceLine y={hi52} stroke="#8fc3e8" strokeDasharray="4 4" label={{ value: "52w high", fill: "#8fc3e8", fontSize: 10 }} />}
              <Line dataKey="close" dot={false} stroke="#c8c8c8" strokeWidth={1.1} name="close" />
              <Line dataKey="ema50" dot={false} stroke="#4d9fe0" strokeWidth={1} name="EMA50" />
              <Line dataKey="ema200" dot={false} stroke="#b58b3c" strokeWidth={1.2} name="EMA200" />
            </LineChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
}

export default function MountedCharts({ symbols }) {
  if (!symbols.length) {
    return (
      <div className="sub">
        Nothing mounted yet — click the ☆ in the scan table (or the watchlist) to add a
        stock and render its chart + momentum trigger here.
      </div>
    );
  }
  return (
    <div>
      {symbols.map((s) => (
        <MiniChart key={s} symbol={s} />
      ))}
    </div>
  );
}
