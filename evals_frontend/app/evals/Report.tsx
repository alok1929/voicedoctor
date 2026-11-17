"use client";

import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  AudioLines,
  Check,
  Globe,
  Mic,
  Phone,
  PhoneCall,
  Play,
  Radio,
  ShieldCheck,
  Target,
  X,
  Zap,
} from "lucide-react";
import CallDetailSheet from "./CallDetailSheet";
import { ReportData } from "../../lib/types";
import { evalResultStyle } from "../../lib/evalResult";
import { ICON_STROKE } from "../../lib/icons";
import { simulationKindsLabel, simulationSummary, soundScenario } from "../../lib/simulation";

export type { ReportData } from "../../lib/types";

type Tone = "ok" | "warn" | "bad" | "neutral" | "info";

function fmtSecs(v: unknown): string {
  if (v == null || typeof v !== "number") return "—";
  return v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
}

function fmtNum(v: unknown): string {
  return v == null ? "—" : String(v);
}

function fmtPct(v: unknown): string {
  return v == null || typeof v !== "number" ? "—" : `${Math.round(v * 100)}%`;
}

function fmtBool(v: unknown): string {
  if (v == null) return "—";
  return v ? "Yes" : "No";
}

function Badge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

const VAL_ICON = 13;
const CHIP_ICON = 12;

function YesNo({
  v,
  yes = "Yes",
  no = "No",
  badWhenTrue = false,
}: {
  v: boolean;
  yes?: string;
  no?: string;
  badWhenTrue?: boolean;
}) {
  const good = badWhenTrue ? !v : v;
  const Icon = good ? Check : badWhenTrue ? AlertTriangle : X;
  return (
    <span className="inline-val">
      <Icon size={VAL_ICON} strokeWidth={2} />
      {v ? yes : no}
    </span>
  );
}

function judgeBadge(key: string, value: unknown): { text: string; tone: Tone } {
  if (value == null) return { text: "—", tone: "neutral" };
  const v = String(value).toLowerCase();
  if (key === "expected_outcome") {
    const { label, tone } = evalResultStyle(String(value).toLowerCase());
    return { text: label, tone };
  }
  if (key === "language_switch_handling")
    return {
      text: v.replace(/_/g, " "),
      tone: v.includes("pass") ? "ok" : v.includes("fail") ? "warn" : "info",
    };
  if (typeof value === "boolean")
    return { text: value ? "Yes" : "No", tone: value ? "ok" : "bad" };
  if (key === "sentiment")
    return { text: v, tone: v === "positive" ? "ok" : v === "negative" ? "bad" : "neutral" };
  if (key === "verbosity") {
    const n = Number(value);
    return { text: `${value}/5`, tone: n >= 4 ? "ok" : n >= 3 ? "warn" : "bad" };
  }
  if (key === "csat") {
    const n = Number(value);
    return { text: String(value), tone: n >= 70 ? "ok" : n >= 40 ? "warn" : "bad" };
  }
  if (key === "unnecessary_repetition") {
    const n = Number(value);
    return { text: String(value), tone: n === 0 ? "ok" : n <= 2 ? "warn" : "bad" };
  }
  return { text: String(value), tone: "neutral" };
}

function Kpi({ num, lbl }: { num: string; lbl: string }) {
  if (num === "—") return null;
  return (
    <div className="kpi">
      <div className="num">{num}</div>
      <div className="lbl">{lbl}</div>
    </div>
  );
}

function Cell({ k, v }: { k: string; v: string }) {
  if (v === "—") return null;
  return (
    <div className="cell">
      <div className="v">{v}</div>
      <div className="k">{k}</div>
    </div>
  );
}

const KIND_LABELS: Record<string, string> = {
  real_bargein: "Real barge-in",
  fake_noise: "Fake noise",
  lang_switch: "Language switch",
  probe_stop: "Stop command",
  probe_start: "Start command",
  filler_speech: "Filler speech",
  filler_cough: "Cough sound",
  caller_hmm: "Hmm sound",
};

function MRow({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  if (value == null || value === "—") return null;
  return (
    <div className="metric-list-row">
      <div>
        <span className="metric-list-row__label">{label}</span>
        {sub ? <span className="metric-list-row__sub">{sub}</span> : null}
      </div>
      <span className="metric-list-row__value">{value}</span>
    </div>
  );
}

function MPanel({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="panel" style={{ padding: "var(--space-4)" }}>
      <div className="section-head" style={{ marginBottom: "var(--space-2)" }}>
        <span style={{ display: "inline-flex", alignItems: "center" }}>{icon}</span>
        <h3 className="section-head__title">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function agentTurnLatencies(summary: ReportData["summary"]): number[] {
  const raw = summary.agent_response_latencies;
  if (!Array.isArray(raw)) return [];
  return raw.filter((x): x is number => typeof x === "number");
}

type TurnLatencyRow = {
  turn: number;
  latency: number;
  testerLine?: string;
  agentLine?: string;
};

function buildTurnLatencyRows(
  latencies: number[],
  transcript: ReportData["transcript"],
): TurnLatencyRow[] {
  const testerLines = transcript.filter((t) => t.role === "assistant");
  const agentLines = transcript.filter((t) => t.role === "user");
  return latencies.map((latency, i) => ({
    turn: i + 1,
    latency,
    testerLine: testerLines[i + 1]?.content,
    agentLine: agentLines[i + 1]?.content,
  }));
}

function TurnLatencyList({ rows }: { rows: TurnLatencyRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-caption" style={{ marginTop: "var(--space-3)", color: "var(--text-secondary)" }}>
        No turn latencies recorded for this call.
      </p>
    );
  }
  return (
    <div style={{ marginTop: "var(--space-3)" }}>
      <div className="cat-name" style={{ marginBottom: "var(--space-2)" }}>
        Turn-by-turn
      </div>
      <ul className="recs" style={{ margin: 0 }}>
        {rows.map((row) => (
          <li key={row.turn} style={{ marginBottom: "var(--space-2)" }}>
            <div className="metric-list-row">
              <div>
                <span className="metric-list-row__label">Turn {row.turn}</span>
                <span className="metric-list-row__sub">tester speech end → agent speech start</span>
              </div>
              <span className="metric-list-row__value">{fmtSecs(row.latency)}</span>
            </div>
            {row.testerLine ? (
              <div className="metric-list-row__sub" style={{ marginTop: "0.15rem" }}>
                Tester: {row.testerLine.length > 72 ? `${row.testerLine.slice(0, 72)}…` : row.testerLine}
              </div>
            ) : null}
            {row.agentLine ? (
              <div className="metric-list-row__sub">
                Agent: {row.agentLine.length > 72 ? `${row.agentLine.slice(0, 72)}…` : row.agentLine}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

type ReportTab = "evaluation" | "recommendations" | "metrics";

export default function Report({ data }: { data: ReportData }) {
  const [showDetail, setShowDetail] = useState(false);
  const [reportTab, setReportTab] = useState<ReportTab>("evaluation");
  const s = data.summary;
  const m = data.judge.metrics || {};
  const conn = data.connection;
  const ledger = (data.ledger || []).filter((e) => e.correct !== null);
  const turnLatencies = agentTurnLatencies(s);
  const turnLatencyRows = buildTurnLatencyRows(turnLatencies, data.transcript);

  const outcome = m["expected_outcome"]?.value;
  const verdict = outcome
    ? judgeBadge("expected_outcome", outcome)
    : { text: "evaluated", tone: "neutral" as Tone };

  const goalMetDespiteTimeout = data.outcome === "timeout" && outcome === "pass";
  const callChipLabel = goalMetDespiteTimeout
    ? `${data.outcome} (objective met)`
    : data.outcome;
  const callChipWarn = data.outcome !== "completed" && !goalMetDespiteTimeout;

  const sims = data.meta.simulations as Record<string, { enabled?: boolean }> | undefined;
  const { kinds: simKinds, sound: simSound } = simulationSummary(data.meta);
  const simLabel = simulationKindsLabel(simKinds);
  const simScenario = soundScenario(simSound);

  const hasSpeechProbes = s.speech_probe_accuracy != null;
  const bargeInEnabled = sims?.barge_in?.enabled === true;
  const showInterruptionPanel = bargeInEnabled || Boolean(data.meta.test_interruptions);
  const showSpeechProbesPanel = hasSpeechProbes && (bargeInEnabled || Boolean(data.meta.test_interruptions));

  const byCategory: Record<string, string[]> = {};
  for (const key of data.meta.evals) {
    const cat = data.metric_catalog[key]?.category || "Other";
    (byCategory[cat] ||= []).push(key);
  }

  return (
    <div className="report">
      <div className="hero">
        <div className="hero-top">
          <span className="hero-title">Result</span>
          <Badge tone={verdict.tone}>{verdict.text}</Badge>
          <button className="hero-detail-btn" onClick={() => setShowDetail(true)}>
            <Play size={CHIP_ICON} strokeWidth={ICON_STROKE} fill="currentColor" />
            Show transcript &amp; recording
          </button>
        </div>
        {data.judge.overall && <p>{data.judge.overall}</p>}
        <div className="meta-chips">
          {simLabel && (
            <span className="meta-chip info">
              <AudioLines size={CHIP_ICON} strokeWidth={ICON_STROKE} />
              {simLabel}
              {simScenario ? ` · ${simScenario}` : ""}
            </span>
          )}
          <span className="meta-chip">
            <Target size={CHIP_ICON} strokeWidth={ICON_STROKE} />
            {data.meta.objective}
          </span>
          <span className="meta-chip">
            <Phone size={CHIP_ICON} strokeWidth={ICON_STROKE} />
            {data.meta.voicera_number || "—"}
          </span>
          {data.meta.language && (
            <span className="meta-chip">
              <Globe size={CHIP_ICON} strokeWidth={ICON_STROKE} />
              {data.meta.language}
            </span>
          )}
          {data.outcome && (
            <span className={`meta-chip ${callChipWarn ? "warn" : ""}`}>
              <PhoneCall size={CHIP_ICON} strokeWidth={ICON_STROKE} />
              {callChipLabel}
            </span>
          )}
          {conn && (
            <>
              <span className={`meta-chip ${conn.connected ? "" : "warn"}`}>
                {conn.connected ? (
                  <Check size={CHIP_ICON} strokeWidth={2} />
                ) : (
                  <X size={CHIP_ICON} strokeWidth={2} />
                )}
                {conn.connected ? "connected" : "not connected"}
              </span>
              <span className={`meta-chip ${conn.ended_gracefully ? "" : "warn"}`}>
                {conn.ended_gracefully ? (
                  <Check size={CHIP_ICON} strokeWidth={2} />
                ) : (
                  <X size={CHIP_ICON} strokeWidth={2} />
                )}
                {conn.ended_gracefully ? "graceful end" : "not graceful"}
              </span>
              {conn.dropped_midcall && (
                <span className="meta-chip warn">
                  <AlertTriangle size={CHIP_ICON} strokeWidth={ICON_STROKE} />
                  mid-call drop
                </span>
              )}
            </>
          )}
        </div>
      </div>

      {(fmtSecs(s.agent_latency_p50_s) !== "—" ||
        fmtNum(s.voicera_talk_ratio) !== "—" ||
        fmtSecs(s.call_duration_secs) !== "—") ? (
        <div className="kpis">
          <Kpi num={fmtSecs(s.agent_latency_p50_s)} lbl="Agent latency P50" />
          <Kpi num={fmtNum(s.voicera_talk_ratio)} lbl="Agent talk ratio" />
          <Kpi num={fmtSecs(s.call_duration_secs)} lbl="Duration" />
        </div>
      ) : null}

      {/* ── metric overview (panels shown only when relevant) ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: "var(--space-3)",
          margin: "var(--space-4) 0",
        }}
      >
        <MPanel icon={<Zap size={16} strokeWidth={ICON_STROKE} />} title="E2E Response Latency">
          <MRow label="Average" value={fmtSecs(s.agent_latency_avg_s)} />
          <MRow label="Median (P50)" value={fmtSecs(s.agent_latency_p50_s)} />
          <MRow label="P99" value={fmtSecs(s.agent_latency_p99_s)} />
          <MRow
            label="Measured turns"
            sub="first agent greeting excluded"
            value={turnLatencies.length > 0 ? String(turnLatencies.length) : "—"}
          />
          <TurnLatencyList rows={turnLatencyRows} />
        </MPanel>

        {showSpeechProbesPanel ? (
          <MPanel icon={<Mic size={16} strokeWidth={ICON_STROKE} />} title="Speech Probes">
            <MRow label="Stop → agent yield" value={fmtSecs(s.speech_probe_stop_response_latency_s as number | null)} />
            <MRow label="Start → agent yield" value={fmtSecs(s.speech_probe_start_response_latency_s as number | null)} />
            <MRow label="Stop correct" value={s.speech_probe_stop_correct == null ? "—" : <YesNo v={Boolean(s.speech_probe_stop_correct)} />} />
            <MRow label="Start correct" value={s.speech_probe_start_correct == null ? "—" : <YesNo v={Boolean(s.speech_probe_start_correct)} />} />
            <MRow label="Filler false stops" sub="hmm/ho/ha" value={fmtNum(s.speech_probe_filler_false_stops as number | null)} />
            <MRow label="Cough false stop" value={s.speech_probe_cough_false_stop == null ? "—" : <YesNo v={Boolean(s.speech_probe_cough_false_stop)} badWhenTrue />} />
            <MRow label="Probe accuracy" value={fmtPct(s.speech_probe_accuracy as number | null)} />
          </MPanel>
        ) : showInterruptionPanel ? (
          <MPanel icon={<Radio size={16} strokeWidth={ICON_STROKE} />} title="Interruption Handling">
            <MRow label="Detection accuracy" sub="barge-in vs noise" value={fmtPct(s.interruption_detection_accuracy)} />
            <MRow label="Agent talk → interrupt" sub="avg delay into turn" value={fmtSecs(s.barge_in_agent_talk_to_interruption_avg_s)} />
            <MRow label="Interrupt → stop" sub="response latency avg" value={fmtSecs(s.interruption_response_latency_avg_s)} />
            <MRow label="False interruption rate" value={fmtPct(s.false_interruption_rate)} />
          </MPanel>
        ) : null}

        <MPanel icon={<ShieldCheck size={16} strokeWidth={ICON_STROKE} />} title="Reliability & Quality">
          <MRow label="Connection" value={conn ? <YesNo v={conn.connected} yes="Connected" no="Failed" /> : "—"} />
          <MRow label="Graceful termination" value={conn ? <YesNo v={conn.ended_gracefully} /> : "—"} />
          <MRow label="Mid-call drop" value={conn ? <YesNo v={conn.dropped_midcall} badWhenTrue /> : "—"} />
          {(m["language_switch_handling"] || s.language_switches != null) ? (
            <MRow
              label="Language switch"
              value={
                m["language_switch_handling"]
                  ? String(m["language_switch_handling"].value).replace(/_/g, " ")
                  : `${s.language_switches} detected`
              }
            />
          ) : null}
        </MPanel>
      </div>

      <div className="panel">
        <div className="rtabs">
          {(
            [
              ["evaluation", "Evaluation"],
              ["recommendations", "Recommendations"],
              ["metrics", "Measured metrics"],
            ] as [ReportTab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              className={`rtab ${reportTab === id ? "active" : ""}`}
              onClick={() => setReportTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {reportTab === "evaluation" &&
          (data.meta.evals.length > 0 ? (
            Object.entries(byCategory).map(([cat, keys]) => (
              <div className="cat" key={cat}>
                <div className="cat-name">{cat}</div>
                {keys.map((key) => {
                  if (key === "csat") return null;
                  const entry = m[key] || {};
                  if (entry.value == null) return null;
                  const b = judgeBadge(key, entry.value);
                  return (
                    <div className="metric-row" key={key}>
                      <span className="name">{data.metric_catalog[key]?.label || key}</span>
                      <Badge tone={b.tone}>{b.text}</Badge>
                      {entry.reason ? <span className="reason">{entry.reason}</span> : null}
                    </div>
                  );
                })}
              </div>
            ))
          ) : (
            <div className="rtab-empty">No evaluations for this call.</div>
          ))}

        {reportTab === "recommendations" &&
          (data.judge.recommendations?.length > 0 ? (
            <ul className="recs">
              {data.judge.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : (
            <div className="rtab-empty">No recommendations for this call.</div>
          ))}

        {reportTab === "metrics" && (
          <>
            <div className="grid">
              <Cell k="Agent latency avg" v={fmtSecs(s.agent_latency_avg_s)} />
              <Cell k="Agent latency P90" v={fmtSecs(s.agent_latency_p90_s)} />
              <Cell k="Agent latency P95" v={fmtSecs(s.agent_latency_p95_s)} />
              <Cell k="Agent latency P99" v={fmtSecs(s.agent_latency_p99_s)} />
              <Cell k="Measured agent turns" v={turnLatencies.length > 0 ? String(turnLatencies.length) : "—"} />
              <Cell k="STT first transcript" v={fmtSecs(s.avg_stt_ttfb_s)} />
              <Cell k="Tester WPM" v={fmtNum(s.tester_wpm)} />
              <Cell k="Agent WPM" v={fmtNum(s.voicera_wpm)} />
              <Cell k="Agent interrupts tester" v={fmtNum(s.voicera_interrupts_tester)} />
              <Cell k="Tester interrupts agent" v={fmtNum(s.tester_interrupts_voicera)} />
              {showInterruptionPanel ? (
                <>
                  <Cell k="Interruption detection accuracy" v={fmtPct(s.interruption_detection_accuracy)} />
                  <Cell
                    k="Agent talk → interrupt (avg)"
                    v={fmtSecs(s.barge_in_agent_talk_to_interruption_avg_s)}
                  />
                  <Cell
                    k="Agent talk → interrupt (p99)"
                    v={fmtSecs(s.barge_in_agent_talk_to_interruption_p99_s)}
                  />
                  <Cell
                    k="Interrupt → stop (avg)"
                    v={fmtSecs(s.interruption_response_latency_avg_s)}
                  />
                  <Cell
                    k="Interrupt → stop (p99)"
                    v={fmtSecs(s.interruption_response_latency_p99_s)}
                  />
                  <Cell k="False interruption rate" v={fmtPct(s.false_interruption_rate)} />
                </>
              ) : null}
              {showSpeechProbesPanel ? (
                <>
                  <Cell k="Stop probe latency" v={fmtSecs(s.speech_probe_stop_response_latency_s as number | null)} />
                  <Cell k="Start probe latency" v={fmtSecs(s.speech_probe_start_response_latency_s as number | null)} />
                  <Cell k="Filler false stops" v={fmtNum(s.speech_probe_filler_false_stops as number | null)} />
                  <Cell k="Cough false stop" v={s.speech_probe_cough_false_stop == null ? "—" : s.speech_probe_cough_false_stop ? "yes" : "no"} />
                  <Cell k="Speech probe accuracy" v={fmtPct(s.speech_probe_accuracy as number | null)} />
                </>
              ) : null}
              <Cell k="Language switches" v={fmtNum(s.language_switches)} />
              <Cell k="Connect latency (dial→media)" v={fmtSecs(s.connect_latency_s)} />
              {s.infra_timeout_detected != null ? (
                <Cell k="Infra timeout" v={s.infra_timeout_detected ? "yes" : "no"} />
              ) : null}
            </div>

            <TurnLatencyList rows={turnLatencyRows} />

            {ledger.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <div className="cat-name">Simulation events</div>
                <ul className="recs">
                  {ledger.map((e, i) => (
                    <li key={i}>
                      <span className="inline-val">
                        {e.correct ? (
                          <Check size={VAL_ICON} strokeWidth={2} />
                        ) : (
                          <X size={VAL_ICON} strokeWidth={2} />
                        )}
                        {KIND_LABELS[e.kind] || e.kind} @ {e.offset_s.toFixed(1)}s
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>

      <AnimatePresence>
        {showDetail && (
          <CallDetailSheet key="cds" data={data} onClose={() => setShowDetail(false)} />
        )}
      </AnimatePresence>
    </div>
  );
}
