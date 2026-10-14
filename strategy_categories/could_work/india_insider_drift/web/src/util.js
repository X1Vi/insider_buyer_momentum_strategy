// small shared helpers for the UI
const MONTHS = {
  Jan: "01", Feb: "02", Mar: "03", Apr: "04", May: "05", Jun: "06",
  Jul: "07", Aug: "08", Sep: "09", Oct: "10", Nov: "11", Dec: "12",
};

// "27-May-2025" -> "2025-05-27"
export function isoFromDmY(s) {
  const match = String(s || "").match(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})/);
  if (!match || !MONTHS[match[2]]) return null;
  return `${match[3]}-${MONTHS[match[2]]}-${match[1].padStart(2, "0")}`;
}

export function inr(v) {
  v = Number(v) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`;
  return `₹${Math.round(v)}`;
}

export function pct(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;
}

export function rupees(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}
