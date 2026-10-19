import { mlDirection, mlText } from "./momentumScores.js";

export default function MlCell({ entry }) {
  const direction = mlDirection(entry);
  const up = entry ? Math.round((entry.p_up ?? entry.score ?? 0) * 100) : null;
  const down = entry ? Math.round((entry.p_down ?? entry.score_down ?? 0) * 100) : null;
  const title = entry
    ? `L ${up}% / S ${down}% · as of ${entry.date}`
    : "No ML score for this symbol";
  const color = direction === "long" ? "#71cf93" : direction === "short" ? "#ec746d" : undefined;
  return <td style={color ? { color } : undefined} title={title}>{mlText(entry)}</td>;
}
