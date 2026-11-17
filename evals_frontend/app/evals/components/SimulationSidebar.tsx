"use client";

import { ChevronDown, ChevronUp, Settings2 } from "lucide-react";
import { Button, SegmentedControl, Stepper } from "../../../components/ui";
import { ICON_SIZE, ICON_STROKE } from "../../../lib/icons";
import { SIM_META, SIM_ORDER, type SimCounts, type SimType } from "./simTypes";

type Props = {
  selectedSim: SimType;
  simCounts: SimCounts;
  onSelect: (simType: SimType) => void;
  onInc: (simType: SimType) => void;
  onDec: (simType: SimType) => void;
  evalPresets: string[];
  evals: string;
  onEvalsChange: (value: string) => void;
  maxMinutes: number;
  onMaxMinutesChange: (value: number) => void;
  advancedOpen: boolean;
  onAdvancedToggle: () => void;
};

export default function SimulationSidebar({
  selectedSim,
  simCounts,
  onSelect,
  onInc,
  onDec,
  evalPresets,
  evals,
  onEvalsChange,
  maxMinutes,
  onMaxMinutesChange,
  advancedOpen,
  onAdvancedToggle,
}: Props) {
  const totalCalls = SIM_ORDER.reduce((n, t) => n + simCounts[t], 0);
  const queuedLines = SIM_ORDER.filter((t) => simCounts[t] > 0).map(
    (t) => `${SIM_META[t].label} ×${simCounts[t]}`
  );

  return (
    <aside className="sim-picker__sidebar" aria-label="Simulation types">
      <p className="sim-picker__nav-label">Simulations</p>
      <ul className="sim-picker__list">
        {SIM_ORDER.map((simType) => {
          const { Icon, label, desc } = SIM_META[simType];
          const count = simCounts[simType];
          const selected = selectedSim === simType;
          const active = count > 0;

          return (
            <li
              key={simType}
              className={`sim-picker__list-item${selected ? " sim-picker__list-item--selected" : ""}${
                active ? " sim-picker__list-item--active" : ""
              }`}
            >
              <button
                type="button"
                className="sim-picker__item"
                onClick={() => onSelect(simType)}
                aria-current={selected ? "true" : undefined}
              >
                <span className="sim-picker__item-icon" aria-hidden>
                  <Icon size={ICON_SIZE} strokeWidth={ICON_STROKE} />
                </span>
                <span className="sim-picker__item-body">
                  <span className="sim-picker__item-label">{label}</span>
                  <span className="sim-picker__item-desc">{desc}</span>
                </span>
              </button>
              {selected ? (
                <div className="sim-picker__stepper-wrap">
                  <Stepper
                    value={count}
                    active={active}
                    onDec={() => onDec(simType)}
                    onInc={() => onInc(simType)}
                  />
                </div>
              ) : active ? (
                <span className="sim-picker__badge" aria-label={`${count} call${count !== 1 ? "s" : ""}`}>
                  {count}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>

      <div className="sim-picker__footer">
        {totalCalls === 0 ? (
          <span className="sim-picker__footer-count">No calls queued</span>
        ) : (
          <>
            <span className="sim-picker__footer-count">
              {totalCalls} call{totalCalls !== 1 ? "s" : ""} queued
            </span>
            <span className="sim-picker__footer-types">{queuedLines.join(" · ")}</span>
          </>
        )}
      </div>

      <div className="sim-picker__advanced">
        <Button
          variant="ghost"
          size="sm"
          className="sim-picker__advanced-toggle"
          onClick={onAdvancedToggle}
          aria-expanded={advancedOpen}
        >
          <Settings2 size={13} strokeWidth={ICON_STROKE} />
          Advanced settings
          {advancedOpen ? (
            <ChevronUp size={13} strokeWidth={ICON_STROKE} />
          ) : (
            <ChevronDown size={13} strokeWidth={ICON_STROKE} />
          )}
        </Button>
        {advancedOpen && (
          <div className="sim-picker__advanced-body">
            <div>
              <p className="text-label">Evals preset</p>
              <SegmentedControl
                options={evalPresets.map((p) => ({ value: p, label: p }))}
                value={evals}
                onChange={onEvalsChange}
              />
            </div>
            <div>
              <p className="text-label">Max call duration</p>
              <div className="sim-picker__duration-row">
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={maxMinutes}
                  onChange={(e) => onMaxMinutesChange(Number(e.target.value))}
                />
                <span className="text-caption">min</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
