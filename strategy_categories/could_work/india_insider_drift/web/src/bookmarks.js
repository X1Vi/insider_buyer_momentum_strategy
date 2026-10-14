import { useEffect, useState } from "react";

// Bookmarks are stored in the browser (localStorage) — no backend needed, and
// nothing leaves the machine. All symbols are upper-cased for consistency.
const KEY = "insider_bookmarks";
// Optional priority per bookmark (1..5), kept in a separate key for back-compat.
const KEY_PRI = "insider_bookmark_priority";
const DEFAULT_PRIORITY = 3;

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

function readPriority() {
  try {
    const raw = localStorage.getItem(KEY_PRI);
    const obj = raw ? JSON.parse(raw) : {};
    return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
  } catch {
    return {};
  }
}

function writePriority(map) {
  try {
    localStorage.setItem(KEY_PRI, JSON.stringify(map));
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event("bookmarks-changed"));
}

export function useBookmarks() {
  const [bookmarks, setBookmarks] = useState(() => new Set(read()));
  const [priority, setPriorityMap] = useState(() => readPriority());

  useEffect(() => {
    const sync = () => {
      setBookmarks(new Set(read()));
      setPriorityMap(readPriority());
    };
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
    if (!next.includes(up)) {
      const map = readPriority();
      if (up in map) {
        delete map[up];
        writePriority(map);
      }
    }
  };

  const has = (symbol) => bookmarks.has(String(symbol).toUpperCase());

  const getPriority = (symbol) => {
    const p = priority[String(symbol).toUpperCase()];
    return Number.isFinite(p) ? p : DEFAULT_PRIORITY;
  };

  const setPriority = (symbol, value) => {
    const map = readPriority();
    map[String(symbol).toUpperCase()] = value;
    writePriority(map);
  };

  const list = [...bookmarks].sort();
  const sorted = [...bookmarks].sort(
    (a, b) => getPriority(b) - getPriority(a) || a.localeCompare(b)
  );

  return { bookmarks, list, sorted, toggle, has, getPriority, setPriority };
}
