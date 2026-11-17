import "./ui.css";

interface StepperProps {
  value: number;
  onDec: () => void;
  onInc: () => void;
  min?: number;
  /** When true, pill uses accent tint; when false, muted gray (same control shape). */
  active?: boolean;
}

export default function Stepper({ value, onDec, onInc, min = 0, active }: StepperProps) {
  const isActive = active ?? value > min;
  return (
    <div
      className={`ui-stepper${isActive ? " ui-stepper--active" : " ui-stepper--muted"}`}
      role="group"
      aria-label="Count stepper"
    >
      <button
        type="button"
        className="ui-stepper__btn"
        onClick={onDec}
        disabled={value <= min}
        aria-label="Decrease"
      >
        −
      </button>
      <span className={`ui-stepper__value${isActive ? " ui-stepper__value--active" : ""}`}>
        {value}
      </span>
      <button
        type="button"
        className="ui-stepper__btn"
        onClick={onInc}
        aria-label="Increase"
      >
        +
      </button>
    </div>
  );
}
