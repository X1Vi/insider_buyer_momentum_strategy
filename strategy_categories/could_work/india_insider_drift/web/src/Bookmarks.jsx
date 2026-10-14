import { useBookmarks } from "./bookmarks.js";

// "Bookmarks" page: the stocks you starred, stored locally in the browser.
export default function Bookmarks({ onPick }) {
  const { sorted, toggle, getPriority, setPriority } = useBookmarks();

  return (
    <div>
      <div className="controls">
        <span className="badge">{sorted.length} bookmarked</span>
        <span className="sub inline">
          Saved in this browser (localStorage). Set a priority (1–5); the list sorts by it.
        </span>
      </div>

      {sorted.length === 0 ? (
        <div className="card">
          <div className="sub">
            No bookmarks yet — click the ☆ next to any stock on the
            <b> Strategy watchlist</b> or <b>Insider buyers</b> tabs to save it here.
          </div>
        </div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Priority</th>
                <th>Symbol</th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s}>
                  <td>
                    <select
                      value={getPriority(s)}
                      title="priority (5 = highest)"
                      onChange={(e) => setPriority(s, Number(e.target.value))}
                    >
                      {[1, 2, 3, 4, 5].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <strong>{s}</strong>
                  </td>
                  <td>
                    <button onClick={() => onPick?.(s)}>chart</button>
                  </td>
                  <td>
                    <button onClick={() => toggle(s)}>remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
