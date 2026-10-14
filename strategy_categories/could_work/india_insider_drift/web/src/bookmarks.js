import { useEffect, useState } from "react";

// Bookmarks are stored in the browser (localStorage) — no backend needed, and
// nothing leaves the machine. All symbols are upper-cased for consistency.
const KEY = "insider_bookmarks";

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
    /* ignore quota / private mode */
  }
  window.dispatchEvent(new Event("bookmarks-changed"));
}

export function useBookmarks() {
  const [bookmarks, setBookmarks] = useState(() => new Set(read()));

  useEffect(() => {
    const sync = () => setBookmarks(new Set(read()));
    window.addEventListener("bookmarks-changed", sync);
    window.addEventListener("storage", sync); // other tabs
    return () => {
      window.removeEventListener("bookmarks-changed", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const toggle = (symbol) => {
    const up = String(symbol).toUpperCase();
    const list = read();
    const next = list.includes(up) ? list.filter((s) => s !== up) : [...list, up];
    write(next);
  };

  const has = (symbol) => bookmarks.has(String(symbol).toUpperCase());

  return { bookmarks, list: [...bookmarks].sort(), toggle, has };
}
