import PriceChart from "./PriceChart.jsx";
import Buyers from "./Buyers.jsx";
import Momentum from "./Momentum.jsx";
import Bookmarks from "./Bookmarks.jsx";
import Scan from "./Scan.jsx";
import { useBookmarks } from "./bookmarks.js";
import { usePersistentState } from "./persist.js";

export default function App() {
  // View + chart selection persist across reloads (localStorage).
  const [view, setView] = usePersistentState("view", "momentum");
  const [symbol, setSymbol] = usePersistentState("symbol", "TFCILTD");
  const [range, setRange] = usePersistentState("range", "10y");
  const { list } = useBookmarks();

  const VIEWS = ["chart", "buyers", "momentum", "scan", "bookmarks"];
  const safeView = VIEWS.includes(view) ? view : "momentum";

  const pick = (s) => {
    setSymbol(s);
    setView("chart");
  };

  return (
    <div className="wrap">
      <h1>Insider momentum watch</h1>
      <div className="sub">
        Rust fetches qualifying NSE insider buyers, then prices only those stocks through Groww.
        Both feeds are cached for 24 hours; this UI only fetches JSON and draws. Bookmarks,
        mounts, the open tab/symbol and every filter are saved in your browser and restored on
        reload.
      </div>

      <div className="tabs">
        <button className={safeView === "chart" ? "active" : ""} onClick={() => setView("chart")}>
          Chart
        </button>
        <button className={safeView === "buyers" ? "active" : ""} onClick={() => setView("buyers")}>
          Insider buyers
        </button>
        <button className={safeView === "momentum" ? "active" : ""} onClick={() => setView("momentum")}>
          Strategy watchlist
        </button>
        <button className={safeView === "scan" ? "active" : ""} onClick={() => setView("scan")}>
          Momentum scan
        </button>
        <button className={safeView === "bookmarks" ? "active" : ""} onClick={() => setView("bookmarks")}>
          ★ Bookmarks{list.length ? ` (${list.length})` : ""}
        </button>
      </div>

      {safeView === "buyers" && <Buyers onPick={pick} />}
      {safeView === "momentum" && <Momentum onPick={pick} />}
      {safeView === "scan" && <Scan onPick={pick} />}
      {safeView === "bookmarks" && <Bookmarks onPick={pick} />}
      {safeView === "chart" && (
        <PriceChart symbol={symbol} setSymbol={setSymbol} range={range} setRange={setRange} />
      )}

      <div className="sub">
        Read-only. No API keys in the frontend; the Rust service cannot place orders.
      </div>
    </div>
  );
}
