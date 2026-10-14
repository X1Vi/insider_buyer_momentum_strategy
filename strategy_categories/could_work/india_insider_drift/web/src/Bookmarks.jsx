import { useBookmarks } from "./bookmarks.js";

// "Bookmarks" page: the stocks you starred, stored locally in the browser.
export default function Bookmarks({ onPick }) {
  const { list, toggle } = useBookmarks();

  return (
    <div>
      <div className="controls">
        <span className="badge">{list.length} bookmarked</span>
        <span className="sub inline">
          Saved in this browser (localStorage). No account, nothing sent anywhere.
        </span>
      </div>

      {list.length === 0 ? (
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
                <th>Symbol</th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s}>
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
