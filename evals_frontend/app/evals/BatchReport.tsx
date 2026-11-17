"use client";

import { useState } from "react";
import Report from "./Report";
import { ReportData } from "../../lib/types";
import { EvalResultPill, evalResultFromReport, evalResultLabel } from "../../lib/evalResult";
import type { SimType } from "./components/simTypes";

type CallState = { id: string; report: ReportData | null; simType?: SimType };

const SIM_LABELS: Record<string, string> = {
  baseline: "Baseline",
  ambient_noise: "Ambient noise",
  barge_in: "Barge-in",
  language_switch: "Language switch",
};

function avg(xs: (number | null | undefined)[]): number | null {
  const v = xs.filter((x): x is number => typeof x === "number");
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
function sum(xs: (number | null | undefined)[]): number {
  return xs.reduce((a: number, b) => a + (typeof b === "number" ? b : 0), 0);
}
function num(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}
function fmtSecs(v: number | null): string {
  if (v == null) return "—";
  return v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
}
function fmtPct(v: number | null): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function Kpi({ num: n, lbl }: { num: string; lbl: string }) {
  return (
    <div className="kpi">
      <div className="num">{n}</div>
      <div className="lbl">{lbl}</div>
    </div>
  );
}

export default function BatchReport({
  calls,
  settled = false,
}: {
  calls: CallState[];
  settled?: boolean;
}) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  const total = calls.length;
  const reports = calls.map((c) => c.report).filter((r): r is ReportData => r != null);
  const ready = reports.length;

  const sums = reports.map((r) => r.summary);
  const completed = reports.filter((r) => r.outcome === "completed").length;
  const disconnRate = ready ? (ready - completed) / ready : null;

  const attempts = sum(sums.map((s) => num(s.tester_interrupts_voicera)));
  const yields = sum(sums.map((s) => num(s.barge_in_yields)));
  const bargeAcc = attempts ? yields / attempts : null;

  // Tally pass/fail verdicts from the judge.
  const outcomes: Record<string, number> = {};
  for (const r of reports) {
    const key = evalResultLabel(evalResultFromReport(r));
    outcomes[key] = (outcomes[key] || 0) + 1;
  }

  // Max connect latency exposes serialization: if calls truly ran in parallel they all
  // connect near-instantly; a large max means later calls waited for a free channel.
  const connectLatencies = sums.map((s) => num(s.connect_latency_s)).filter((x): x is number => x != null);
  const maxConnect = connectLatencies.length ? Math.max(...connectLatencies) : null;

  const agg = {
    agentLatAvg: avg(sums.map((s) => num(s.agent_latency_avg_s))),
    agentLatP90: avg(sums.map((s) => num(s.agent_latency_p90_s))),
    interruptAfter: avg(sums.map((s) => num(s.tester_interrupt_after_avg_s))),
    yieldAfter: avg(sums.map((s) => num(s.voicera_stop_after_interruption_avg_s))),
    reresponse: avg(sums.map((s) => num(s.voicera_reresponse_after_interrupt_avg_s))),
    duration: avg(sums.map((s) => num(s.call_duration_secs))),
  };

  return (
    <div className="report">
      <div className="hero">
        <div className="hero-top">
          <span className="hero-title">Eval suite — {total} sequential calls</span>
          <span className="meta-chip" style={{ marginLeft: "auto" }}>
            {ready}/{total} finished
          </span>
        </div>
        <div className="meta-chips">
          {Object.entries(outcomes).map(([k, v]) => (
            <span
              key={k}
              className={`meta-chip ${
                k === "Pass" ? "" : k === "Not passed" ? "warn" : k === "Needs review" ? "info" : ""
              }`}
            >
              {k}: {v}
            </span>
          ))}
        </div>
      </div>

      <div className="kpis">
        <Kpi num={fmtPct(disconnRate)} lbl="Disconnection rate" />
        <Kpi num={fmtSecs(agg.agentLatAvg)} lbl="Avg agent latency" />
        <Kpi num={fmtSecs(agg.agentLatP90)} lbl="Avg agent P90" />
        <Kpi num={fmtPct(bargeAcc)} lbl="Barge-in accuracy" />
        <Kpi num={fmtSecs(maxConnect)} lbl="Max connect latency" />
        <Kpi num={fmtSecs(agg.duration)} lbl="Avg duration" />
      </div>

      <div className="panel">
        <h3>Aggregate across calls</h3>
        <div className="grid">
          <div className="cell">
            <div className="v">{fmtSecs(agg.interruptAfter)}</div>
            <div className="k">Tester interrupts after</div>
          </div>
          <div className="cell">
            <div className="v">{fmtSecs(agg.yieldAfter)}</div>
            <div className="k">Agent yield after interrupt</div>
          </div>
          <div className="cell">
            <div className="v">{fmtSecs(agg.reresponse)}</div>
            <div className="k">Agent re-response after interrupt</div>
          </div>
          <div className="cell">
            <div className="v">
              {completed}/{ready}
            </div>
            <div className="k">Completed cleanly</div>
          </div>
          <div className="cell">
            <div className="v">
              {yields}/{attempts}
            </div>
            <div className="k">Barge-ins yielded</div>
          </div>
        </div>
      </div>

      {/* Per-call reports (click to expand) */}
      <div className="panel">
        <h3>Individual calls</h3>
        <div className="grouped-list">
        {calls.map((c, i) => (
          <div key={c.id} className="batch-call">
            <button className="batch-call-head" onClick={() => setOpenIdx(openIdx === i ? null : i)}>
              <span>Call {i + 1}{c.simType ? ` — ${SIM_LABELS[c.simType] || c.simType}` : ""}</span>
              {c.report ? (
                <EvalResultPill result={evalResultFromReport(c.report)} />
              ) : (
                <span className="meta-chip">{settled ? "no report" : "running…"}</span>
              )}
              <span className="batch-call-id">{c.id.slice(0, 8)}</span>
              <span className={`batch-caret${openIdx === i ? " batch-caret--open" : ""}`}>▼</span>
            </button>
            <div
              className="batch-call-body"
              style={{ maxHeight: openIdx === i && c.report ? 5000 : 0, opacity: openIdx === i && c.report ? 1 : 0 }}
            >
              {openIdx === i && c.report && (
                <div className="batch-call-body-inner">
                  <Report data={c.report} />
                </div>
              )}
            </div>
          </div>
        ))}
        </div>
      </div>
    </div>
  );
}
