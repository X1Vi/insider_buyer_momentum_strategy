import { useEffect, useState } from "react";

// "Mounts" = stocks you pinned from the Momentum scan to render their charts.
// Stored in the browser (localStorage), same idea as bookmarks.
const KEY = "insider_mounts";

function read() {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.map((s) => String(s).toUpperCase()) : [];
  } catch {
    return [];
  }
}
function write(list) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event("mounts-changed"));
}

export function useMounts() {
  const [set, setSet] = useState(() => new Set(read()));
  useEffect(() => {
    const sync = () => setSet(new Set(read()));
    window.addEventListener("mounts-changed", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("mounts-changed", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const toggle = (symbol) => {
    const up = String(symbol).toUpperCase();
    const list = read();
    write(list.includes(up) ? list.filter((s) => s !== up) : [...list, up]);
  };
  const has = (symbol) => set.has(String(symbol).toUpperCase());
  const clear = () => write([]);
  return { mounts: set, list: [...set].sort(), toggle, has, clear };
}
