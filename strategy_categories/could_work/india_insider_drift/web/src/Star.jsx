import { useBookmarks } from "./bookmarks.js";

// A little star toggle. Stops click propagation so it works inside clickable rows.
export default function Star({ symbol }) {
  const { has, toggle } = useBookmarks();
  const on = has(symbol);
  return (
    <button
      className={`star ${on ? "on" : ""}`}
      title={on ? "remove bookmark" : "bookmark this stock"}
      aria-label={on ? "remove bookmark" : "bookmark"}
      onClick={(e) => {
        e.stopPropagation();
        toggle(symbol);
      }}
    >
      {on ? "★" : "☆"}
    </button>
  );
}
