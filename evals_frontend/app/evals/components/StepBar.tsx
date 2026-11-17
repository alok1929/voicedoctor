const STEPS = ["Pick simulations", "Configure calls", "Results"];

export default function StepBar({ current }: { current: number }) {
  return (
    <div className="step-bar">
      {STEPS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div key={i} className="step-bar__item">
            <div style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
              <div className={`step-bar__dot${done || active ? " step-bar__dot--done" : ""}${active ? " step-bar__dot--active" : ""}`}>
                {done ? "✓" : i + 1}
              </div>
              <span className={`step-bar__label${active ? " step-bar__label--active" : ""}`}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`step-bar__line${done ? " step-bar__line--done" : ""}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
