import "./ui.css";

interface SliderProps {
  label: string;
  value: number;
  display?: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  caption?: string;
}

export default function Slider({
  label,
  value,
  display,
  min,
  max,
  step,
  onChange,
  caption,
}: SliderProps) {
  return (
    <div className="ui-slider">
      <div className="ui-slider__head">
        <span className="ui-slider__label">{label}</span>
        <span className="ui-slider__value">{display ?? value}</span>
      </div>
      <input
        type="range"
        className="ui-slider__input"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {caption && <p className="ui-slider__caption">{caption}</p>}
    </div>
  );
}
