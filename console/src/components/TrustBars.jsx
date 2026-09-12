const COMPONENTS = [
  ["evidence_quality", "Evidence quality"],
  ["measurement_margin", "Measurement margin"],
  ["model_confidence", "Model confidence"],
  ["rule_determinacy", "Rule determinacy"],
  ["precedent_consistency", "Precedent consistency"],
];

const LOW_THRESHOLD = 0.4;

/** Section 5.7/5.8: trust is five separate components, never a single
 * opaque score. Rendered as five bars so a steward can see *which*
 * dimension is weak, not just a blended number.
 */
export default function TrustBars({ trust }) {
  const ambiguous = trust.conformal_set.length > 1;

  return (
    <div className="trust-vector">
      <div className="trust-vector-title">Trust decomposition</div>
      {COMPONENTS.map(([key, label]) => {
        const value = trust[key];
        const low = value < LOW_THRESHOLD;
        return (
          <div className="trust-row" key={key}>
            <span className="trust-label">{label}</span>
            <span className="trust-track">
              <span
                className="trust-fill"
                data-low={low}
                style={{ width: `${Math.round(value * 100)}%` }}
              />
            </span>
            <span className="trust-value">{value.toFixed(2)}</span>
          </div>
        );
      })}
      <div className="trust-row">
        <span className="trust-label">Scalar (ranking only)</span>
        <span className="trust-track">
          <span
            className="trust-fill"
            data-low={trust.scalar < LOW_THRESHOLD}
            style={{ width: `${Math.round(trust.scalar * 100)}%` }}
          />
        </span>
        <span className="trust-value">{trust.scalar.toFixed(2)}</span>
      </div>
      <div className="conformal-note" data-ambiguous={ambiguous}>
        {ambiguous
          ? `Conformal set: ${trust.conformal_set.join(", ")} (ambiguous)`
          : `Conformal set: ${trust.conformal_set[0]}`}
      </div>
    </div>
  );
}
