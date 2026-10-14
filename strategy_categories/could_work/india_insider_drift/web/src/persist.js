import { useEffect, useState } from "react";

// Persist UI state in the browser so a page reload (or reopening the tab) restores
// exactly what the user was looking at. Uses localStorage; nothing leaves the
// machine. All keys are namespaced with `insider_ui_`.
const PREFIX = "insider_ui_";

export function usePersistentState(key, initial) {
  const storageKey = PREFIX + key;
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw == null) return initial;
      return JSON.parse(raw);
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      /* quota / private mode — ignore */
    }
  }, [storageKey, value]);

  // keep multiple tabs in sync (optional but cheap)
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key !== storageKey || e.newValue == null) return;
      try {
        setValue(JSON.parse(e.newValue));
      } catch {
        /* ignore */
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [storageKey]);

  return [value, setValue];
}
