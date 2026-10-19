import { useEffect, useState } from "react";

let shared = null;
let sharedPromise = null;

// Static score file produced by momentum_ml/build_scores.py. The app only
// reads it; no model inference runs in the browser.
function loadScores() {
  if (shared) return Promise.resolve(shared);
  if (!sharedPromise) {
    sharedPromise = fetch("/momentum_ml_scores.json", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`ML scores ${response.status}`);
        return response.json();
      })
      .then((data) => {
        shared = data;
        return data;
      })
      .catch((error) => {
        sharedPromise = null;
        throw error;
      });
  }
  return sharedPromise;
}

export function useMomentumScores() {
  const [data, setData] = useState(shared);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    loadScores()
      .then((value) => active && setData(value))
      .catch((requestError) => active && setError(requestError.message));
    return () => {
      active = false;
    };
  }, []);
  return { data, error, scoreFor: (symbol) => data?.scores?.[symbol] || null };
}

export function mlDirection(entry) {
  if (!entry) return "neutral";
  if (entry.direction) return entry.direction;
  const up = entry.p_up ?? entry.score ?? 0;
  const down = entry.p_down ?? entry.score_down ?? 0;
  if (up >= 0.4 && up >= down) return "long";
  if (down >= 0.4 && down > up) return "short";
  return "neutral";
}

export function mlStrength(entry) {
  if (!entry) return 0;
  return entry.strength ?? Math.max(
    entry.p_up ?? entry.score ?? 0,
    entry.p_down ?? entry.score_down ?? 0,
  );
}

export function mlText(entry) {
  const direction = mlDirection(entry);
  if (direction === "neutral") return "—";
  const probability = direction === "long"
    ? (entry.p_up ?? entry.score ?? 0)
    : (entry.p_down ?? entry.score_down ?? 0);
  return `${direction === "long" ? "L" : "S"} ${Math.round(probability * 100)}%`;
}
