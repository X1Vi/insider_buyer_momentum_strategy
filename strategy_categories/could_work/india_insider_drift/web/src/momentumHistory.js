import { useEffect, useMemo, useState } from "react";

let shared = null;
let sharedPromise = null;

function loadHistory() {
  if (shared) return Promise.resolve(shared);
  if (!sharedPromise) {
    sharedPromise = fetch("/momentum_ml_history.json", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`ML history ${response.status}`);
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

export function useMomentumHistory() {
  const [data, setData] = useState(shared);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    loadHistory()
      .then((value) => active && setData(value))
      .catch((requestError) => active && setError(requestError.message));
    return () => {
      active = false;
    };
  }, []);

  const pointsFor = (symbol) => data?.by_symbol?.[symbol] || [];
  return { data, error, pointsFor };
}

export function useMomentumPoints(symbol) {
  const history = useMomentumHistory();
  const points = useMemo(
    () => (symbol ? history.pointsFor(symbol) : []),
    [history, symbol],
  );
  return { ...history, points };
}
