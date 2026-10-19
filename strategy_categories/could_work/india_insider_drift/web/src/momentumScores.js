import { useEffect, useState } from "react";

let shared = null;
let sharedPromise = null;

// Static score file produced by momentum_ml/build_scores.py. The app only
// reads it; no model inference runs in the browser.
function loadScores() {
  if (shared) return Promise.resolve(shared);
  if (!sharedPromise) {
    sharedPromise = fetch("/momentum_ml_scores.json")
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

