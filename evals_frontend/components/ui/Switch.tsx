import "./ui.css";

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  sub?: string;
  id?: string;
}

export default function Switch({ checked, onChange, label, sub, id }: SwitchProps) {
  const switchId = id || `switch-${label?.replace(/\s/g, "-").toLowerCase()}`;
  return (
    <label className="ui-switch-row" htmlFor={switchId}>
      <div className="ui-switch-row__text">
        {label && <span className="ui-switch-row__label">{label}</span>}
        {sub && <span className="ui-switch-row__sub">{sub}</span>}
      </div>
      <button
        id={switchId}
        type="button"
        role="switch"
        aria-checked={checked}
        className={`ui-switch${checked ? " ui-switch--on" : ""}`}
        onClick={() => onChange(!checked)}
      >
        <span className="ui-switch__knob" />
      </button>
    </label>
  );
}
