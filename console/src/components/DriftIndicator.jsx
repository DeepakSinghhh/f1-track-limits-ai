/** Per-corner override-rate drift: how often stewards have overturned
 * this system's verdict at a given corner, computed client-side from the
 * override log. A rising rate at one corner is a signal the rule
 * config (or the boundary geometry) may be wrong there -- it is not
 * itself a decision about any single finding.
 */
export default function DriftIndicator({ overrides }) {
  const byCorner = new Map();
  for (const rec of overrides) {
    const bucket = byCorner.get(rec.corner) ?? { total: 0, overridden: 0 };
    bucket.total += 1;
    if (rec.human_decision !== rec.system_verdict) bucket.overridden += 1;
    byCorner.set(rec.corner, bucket);
  }

  const corners = [...byCorner.entries()].sort((a, b) => a[0] - b[0]);
  if (corners.length === 0) return null;

  return (
    <div className="drift-banner">
      {corners.map(([corner, { total, overridden }]) => {
        const rate = overridden / total;
        const severity = rate >= 0.4 ? "high" : rate >= 0.2 ? "medium" : "low";
        return (
          <span className="drift-chip" data-severity={severity} key={corner}>
            <span className="corner-label">turn {corner}</span>
            <span className="rate">{Math.round(rate * 100)}%</span>
            <span className="corner-label">override rate ({total})</span>
          </span>
        );
      })}
    </div>
  );
}
