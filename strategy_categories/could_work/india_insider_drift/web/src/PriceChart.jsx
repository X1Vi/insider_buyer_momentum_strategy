import { useEffect, useMemo, useState } from "react";
import {
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { inr, isoFromDmY, rupees } from "./util.js";
import Star from "./Star.jsx";
import { useMomentumPoints } from "./momentumHistory.js";
import { mlDirection, mlText, useMomentumScores } from "./momentumScores.js";

const SYMBOLS = [
  "TFCILTD", "SURYAROSNI", "ADANIPORTS", "CHAMBLFERT", "MAHSEAMLES", "JSWSTEEL",
  "GRASIM", "GODREJAGRO", "GODREJIND", "APOLLOTYRE", "DBCORP", "STEL", "NCLIND",
  "NRBBEARING", "NCC", "MANINFRA", "APLLTD", "JSL", "BAJAJHLDNG", "KRISHANA",
  // Symbols carried over from the moneyflow ledger (OSINT/moneyflow) so the same
  // stocks can be plotted in both apps. STEL and INFY are already listed above.
  "SHK", "HCLTECH", "NATCOPHARM", "TEXMOPIPES", "DMART", "SWANCORP", "RESPONIND",
  "AEQUS", "EMBDL", "INFY", "ECLERX", "JMFINANCIL", "DIAMONDYD", "BAJAJFINSV",
  "NAZARA",
];

// Red down-triangle marker for insider SELLS (recharts has no built-in one).
function DownTriangle({ cx, cy, fill }) {
  if (cx == null || cy == null) return null;
  const s = 6;
  return (
    <path
      d={`M ${cx - s} ${cy - s} L ${cx + s} ${cy - s} L ${cx} ${cy + s} Z`}
      fill={fill}
      stroke="white"
      strokeWidth={0.5}
    />
  );
}

// One symbol: price + EMA50/EMA200 + insider BUY (▲) and SELL (▼) markers + RSI,
// and the buys/sells tables. This is the combined long+distribution view.
export default function PriceChart({ symbol, setSymbol, range, setRange }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const ml = useMomentumPoints(symbol);
  const liveScores = useMomentumScores();
  const liveEntry = liveScores.scoreFor(symbol);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr("");
    fetch(`/api/series?symbol=${encodeURIComponent(symbol)}&range=${range}`)
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
  }, [symbol, range]);

  const mlByDate = useMemo(
    () => new Map((ml.points || []).map((point) => [point.date, point])),
    [ml.points],
  );

  const { rows, buyRows, sellRows } = useMemo(() => {
    if (!data) return { rows: [], buyRows: [], sellRows: [] };
    const firstTradingDate = (target, strictlyAfter = false) =>
      data.dates.find((date) => strictlyAfter ? date > target : date >= target);

    const bucketByTradeDate = (events, key) => {
      const byDate = new Map();
      for (const e of events) {
        const tradeDate = firstTradingDate(isoFromDmY(e.trade_date));
        if (!tradeDate) continue;
        const prev = byDate.get(tradeDate) || { value: 0, qty: 0, names: [] };
        prev.value += Number(e.value_inr) || 0;
        prev.qty += Number(e.qty) || 0;
        prev.names.push(`${e.buyer} (${e.role})`);
        byDate.set(tradeDate, prev);
      }
      return byDate;
    };

    const purchaseByDate = bucketByTradeDate(data.buys || []);
    const saleByDate = bucketByTradeDate(data.sells || []);

    // Public-disclosure dates stay separate from the trade date: this is when the
    // strategy could first know that the private purchase had happened.
    const disclosureByDate = new Map();
    for (const b of data.buys || []) {
      const disclosureIso = isoFromDmY(b.disclosure_date)
        || (b.disclosure_date || "").slice(0, 10);
      const time = String(b.disclosure_date || "").match(/\s(\d{1,2}):(\d{2})/);
      const afterClose = time && (Number(time[1]) > 15
        || (Number(time[1]) === 15 && Number(time[2]) >= 30));
      const disclosureDate = firstTradingDate(disclosureIso, afterClose);
      if (disclosureDate) {
        const prev = disclosureByDate.get(disclosureDate) || { value: 0, names: [] };
        prev.value += Number(b.value_inr) || 0;
        prev.names.push(`${b.buyer} (${b.role})`);
        disclosureByDate.set(disclosureDate, prev);
      }
    }

    const rows = data.dates.map((date, i) => {
      const purchase = purchaseByDate.get(date);
      const sale = saleByDate.get(date);
      const disclosure = disclosureByDate.get(date);
      const mlPoint = mlByDate.get(date);
      const estimatedPurchasePrice = purchase?.qty > 0
        ? purchase.value / purchase.qty
        : null;
      const estimatedSalePrice = sale?.qty > 0 ? sale.value / sale.qty : null;
      return {
        date,
        close: data.close[i],
        ema50: data.ema50[i],
        ema200: data.ema200[i],
        rsi: data.rsi[i],
        insiderPurchase: purchase ? (estimatedPurchasePrice || data.close[i]) : null,
        purchasePriceEstimated: estimatedPurchasePrice != null,
        purchaseValue: purchase?.value || null,
        purchaseNames: purchase ? purchase.names.join("; ") : null,
        insiderSale: sale ? (estimatedSalePrice || data.close[i]) : null,
        salePriceEstimated: estimatedSalePrice != null,
        saleValue: sale?.value || null,
        saleNames: sale ? sale.names.join("; ") : null,
        publicDisclosure: disclosure ? data.close[i] : null,
        disclosureValue: disclosure?.value || null,
        disclosureNames: disclosure ? disclosure.names.join("; ") : null,
        mlBuy: mlPoint?.direction === "long" ? data.close[i] : null,
        mlSell: mlPoint?.direction === "short" ? data.close[i] : null,
        mlPoint,
      };
    });
    return { rows, buyRows: data.buys || [], sellRows: data.sells || [] };
  }, [data, mlByDate]);

  const mlBuyCount = (ml.points || []).filter((point) => point.direction === "long").length;
  const mlSellCount = (ml.points || []).filter((point) => point.direction === "short").length;

  const nBuys = buyRows.length;
  const nSells = sellRows.length;
  const buyValue = buyRows.reduce((a, b) => a + (Number(b.value_inr) || 0), 0);
  const sellValue = sellRows.reduce((a, b) => a + (Number(b.value_inr) || 0), 0);
  const netValue = buyValue - sellValue;

  return (
    <div>
      <div className="controls">
        <label>
          Symbol{" "}
          <input className="filterInput" list="buyer-symbols" value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
          <datalist id="buyer-symbols">
            {SYMBOLS.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </datalist>
        </label>
        <label>
          Range{" "}
          <select value={range} onChange={(e) => setRange(e.target.value)}>
            {["1y", "2y", "5y", "10y", "max"].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <Star symbol={symbol} />
        <span className="badge">{nBuys} buys</span>
        <span className="badge">{nSells} sells</span>
        <span className="badge">net {inr(netValue)}</span>
        <span className="badge" title="walk-forward ML points, not insider disclosures">
          ML {mlBuyCount} buy / {mlSellCount} sell
        </span>
        {liveEntry && (
          <span
            className="badge"
            title={`live ML score as of ${liveEntry.date}: L ${Math.round((liveEntry.p_up ?? liveEntry.score ?? 0) * 100)}% / S ${Math.round((liveEntry.p_down ?? liveEntry.score_down ?? 0) * 100)}%`}
            style={{ color: mlDirection(liveEntry) === "long" ? "#f2c14e" : mlDirection(liveEntry) === "short" ? "#b084f5" : undefined }}
          >
            ML now {mlText(liveEntry)}
          </span>
        )}
        {data?.price_source && <span className="sourceBadge">prices: {data.price_source}{data.price_cache_hit ? " · cached" : ""}</span>}
        {loading && <span className="sub">loading…</span>}
        {err && <span className="err">error: {err}</span>}
      </div>

      <div className="card">
        <ResponsiveContainer width="100%" height={440}>
          <ComposedChart data={rows} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#232a33" />
            <XAxis dataKey="date" minTickGap={60} stroke="#8b97a3" />
            <YAxis yAxisId="price" domain={["auto", "auto"]} stroke="#8b97a3" />
            <Tooltip
              contentStyle={{ background: "#161b21", border: "1px solid #2a313a" }}
              formatter={(v, n) => (v == null ? ["-", n] : [Number(v).toFixed(1), n])}
              labelFormatter={(l) => l}
              content={({ active, payload, label }) => {
                if (!active || !payload || !payload.length) return null;
                const p = payload[0].payload;
                return (
                  <div style={{ background: "#161b21", border: "1px solid #2a313a", padding: 8, fontSize: 12 }}>
                    <div><b>{label}</b></div>
                    <div>close {p.close?.toFixed?.(1)}</div>
                    <div>EMA50 {p.ema50?.toFixed?.(1)} · EMA200 {p.ema200?.toFixed?.(1)}</div>
                    {p.purchaseNames && (
                      <div style={{ color: "#9ad29a" }}>
                        INSIDER BUY: {p.purchaseNames}<br />
                        {p.purchasePriceEstimated ? "estimated average" : "close proxy"} {rupees(p.insiderPurchase)} · {inr(p.purchaseValue || 0)}
                      </div>
                    )}
                    {p.saleNames && (
                      <div style={{ color: "#e8a0a0" }}>
                        INSIDER SELL: {p.saleNames}<br />
                        {p.salePriceEstimated ? "estimated average" : "close proxy"} {rupees(p.insiderSale)} · {inr(p.saleValue || 0)}
                      </div>
                    )}
                    {p.disclosureNames && (
                      <div style={{ color: "#8fc3e8" }}>
                        PUBLIC DISCLOSURE: {p.disclosureNames} · {inr(p.disclosureValue || 0)}
                      </div>
                    )}
                    {p.mlPoint && (
                      <div style={{ color: p.mlPoint.direction === "long" ? "#f2c14e" : "#b084f5" }}>
                        ML {p.mlPoint.direction.toUpperCase()} {Math.round(p.mlPoint.strength * 100)}%
                        {p.mlPoint.fwd20 != null && ` · 20d ${(p.mlPoint.fwd20 * 100).toFixed(1)}%`}
                      </div>
                    )}
                  </div>
                );
              }}
            />
            <Legend />
            <Line yAxisId="price" dataKey="close" dot={false} stroke="#c8c8c8" strokeWidth={1.1} name="close" />
            <Line yAxisId="price" dataKey="ema50" dot={false} stroke="#4d9fe0" strokeWidth={1} name="EMA50" />
            <Line yAxisId="price" dataKey="ema200" dot={false} stroke="#b58b3c" strokeWidth={1} name="EMA200" />
            <Scatter yAxisId="price" dataKey="insiderPurchase" fill="#1a9850" name="insider buy (est. avg)" shape="triangle" />
            <Scatter yAxisId="price" dataKey="publicDisclosure" fill="#4d9fe0" name="public disclosure" shape="circle" />
            <Scatter yAxisId="price" dataKey="insiderSale" fill="#d73027" name="insider sell (est. avg)" shape={<DownTriangle />} />
            <Scatter yAxisId="price" dataKey="mlBuy" fill="#f2c14e" name="ML buy (walk-forward)" shape="diamond" />
            <Scatter yAxisId="price" dataKey="mlSell" fill="#b084f5" name="ML sell (walk-forward)" shape="diamond" />
          </ComposedChart>
        </ResponsiveContainer>
        <div className="sub">
          Green ▲ = major insider market purchase; blue ● = the later public disclosure
          (the first point the strategy could know about it); red ▼ = major insider
          market sale. Buy/sell markers sit at disclosed value ÷ quantity (estimated
          batch-average price) on the reported trade date. Gold ◆ / purple ◆ are
          walk-forward ML price points (not insider trades); tooltip shows the
          next-20-session return for historical reference.
          {ml.error && <span className="err"> ML history unavailable: {ml.error}</span>}
        </div>
      </div>

      <div className="card">
        <div className="sub" style={{ marginBottom: 6 }}>RSI(14)</div>
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart data={rows} margin={{ top: 5, right: 20, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#232a33" />
            <XAxis dataKey="date" minTickGap={60} stroke="#8b97a3" />
            <YAxis domain={[0, 100]} stroke="#8b97a3" />
            <ReferenceLine y={70} stroke="#d73027" strokeDasharray="3 3" />
            <ReferenceLine y={30} stroke="#1a9850" strokeDasharray="3 3" />
            <Line dataKey="rsi" dot={false} stroke="#888" strokeWidth={1} name="RSI(14)" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <div className="sub" style={{ marginBottom: 6 }}>
          Insider market purchases — {symbol} ({nBuys}) · {inr(buyValue)}
        </div>
        <table>
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
            {buyRows
              .slice()
              .sort((a, b) => (a.trade_date < b.trade_date ? 1 : -1))
              .map((b, i) => (
                <tr key={i}>
                  <td>{b.trade_date}</td>
                  <td>{(b.disclosure_date || "").slice(0, 10)}</td>
                  <td>{b.buyer}</td>
                  <td>{b.role}</td>
                  <td>{Number(b.qty || 0).toLocaleString("en-IN")}</td>
                  <td title="NSE disclosed transaction value divided by disclosed quantity">
                    {b.estimated_price == null ? "—" : `${rupees(b.estimated_price)} (est.)`}
                  </td>
                  <td>{inr(b.value_inr || 0)}</td>
                </tr>
              ))}
            {nBuys === 0 && (
              <tr>
                <td colSpan={7} className="sub">
                  No major insider buys for {symbol} in the window.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="sub" style={{ marginBottom: 6 }}>
          Insider market sales — {symbol} ({nSells}) · {inr(sellValue)}
        </div>
        <table>
          <thead>
            <tr>
              <th>Trade date</th>
              <th>Disclosure</th>
              <th>Seller</th>
              <th>Role</th>
              <th>Quantity</th>
              <th>Estimated avg price</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {sellRows
              .slice()
              .sort((a, b) => (a.trade_date < b.trade_date ? 1 : -1))
              .map((s, i) => (
                <tr key={i}>
                  <td>{s.trade_date}</td>
                  <td>{(s.disclosure_date || "").slice(0, 10)}</td>
                  <td>{s.buyer}</td>
                  <td>{s.role}</td>
                  <td>{Number(s.qty || 0).toLocaleString("en-IN")}</td>
                  <td title="NSE disclosed transaction value divided by disclosed quantity">
                    {s.estimated_price == null ? "—" : `${rupees(s.estimated_price)} (est.)`}
                  </td>
                  <td>{inr(s.value_inr || 0)}</td>
                </tr>
              ))}
            {nSells === 0 && (
              <tr>
                <td colSpan={7} className="sub">
                  No major insider sales for {symbol} in the window.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
