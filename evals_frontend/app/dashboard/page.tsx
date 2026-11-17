"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  PhoneCall, XCircle, Timer, Star,
  TrendingUp, FlaskConical, ArrowRight, Zap, Radio,
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { Button } from "../../components/ui";
import { ICON_SIZE, ICON_STROKE } from "../../lib/icons";
import { evalsAuthHeaders } from "../../lib/evalsApi";
import { EvalResultPill } from "../../lib/evalResult";

const API = process.env.NEXT_PUBLIC_EVALRA_API || "http://localhost:8100";

interface Summary {
  n: number;
  connection_success_rate: number | null;
  graceful_termination_rate: number | null;
  mid_call_drop_rate: number | null;
  avg_duration_secs: number | null;
  avg_voicera_wpm: number | null;
  outcome_distribution: Record<string, number>;
  baseline_n: number;
  latency_scope?: "baseline" | "all";
  baseline_agent_latency_avg_s: number | null;
  baseline_agent_latency_p50_s: number | null;
  baseline_agent_latency_p99_s: number | null;
  avg_interruption_detection_accuracy: number | null;
  avg_barge_in_agent_talk_to_interruption_avg_s: number | null;
  avg_interruption_response_latency_avg_s: number | null;
  avg_false_interruption_rate: number | null;
  avg_dead_air_rate_per_min: number | null;
}

interface RecentCall {
  call_id: string;
  generated_at: string;
  outcome: string;
  eval_result: string | null;
  voicera_number: string;
  objective: string;
  duration_secs: number | null;
  language: string;
  connection: { connected: boolean; ended_gracefully: boolean; dropped_midcall: boolean } | null;
}

function pct(v: number | null) {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 100)}%`;
}
function ms(v: number | null) {
  if (v === null || v === undefined) return "—";
  return v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
}
function fmt(v: number | null, d = 0) {
  if (v === null || v === undefined) return "—";
  return v.toFixed(d);
}

function KpiCard({
  icon: Icon, label, value, sub,
}: {
  icon: React.ElementType; label: string; value: string; sub?: string;
}) {
  return (
    <div className="kpi-card">
      <div className="kpi-card__label">
        <Icon size={13} strokeWidth={ICON_STROKE} />{label}
      </div>
      <div className="kpi-card__value">{value}</div>
      {sub && <div className="kpi-card__sub">{sub}</div>}
    </div>
  );
}

function MetricRow({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="metric-list-row">
      <div>
        <span className="metric-list-row__label">{label}</span>
        {sub && <span className="metric-list-row__sub">{sub}</span>}
      </div>
      <span className="metric-list-row__value">{value}</span>
    </div>
  );
}

function SectionHead({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <div className="section-head">
      <Icon size={ICON_SIZE} strokeWidth={ICON_STROKE} color="var(--text-secondary)" />
      <h3 className="section-head__title">{title}</h3>
    </div>
  );
}

const OUTCOME_COLORS: Record<string, string> = {
  completed: "var(--success)",
  timeout: "var(--warning)",
  disconnected: "var(--danger)",
  never_connected: "var(--danger)",
  unknown: "var(--text-secondary)",
};

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [recent, setRecent] = useState<RecentCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [sumRes, recRes] = await Promise.all([
          fetch(`${API}/metrics/summary`, { headers: evalsAuthHeaders() }),
          fetch(`${API}/metrics/recent?limit=10`, { headers: evalsAuthHeaders() }),
        ]);
        if (!sumRes.ok || !recRes.ok) throw new Error("Failed to load metrics");
        setSummary(await sumRes.json());
        setRecent(await recRes.json());
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to connect to Evalra backend");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const chartData = summary
    ? Object.entries(summary.outcome_distribution).map(([k, v]) => ({
        name: k.charAt(0).toUpperCase() + k.slice(1),
        count: v,
        color: OUTCOME_COLORS[k] || "var(--text-secondary)",
      }))
    : [];

  return (
    <div className="page-container">
      <div className="reports-header">
        <div>
          <h1 className="page-title" style={{ fontSize: "1.6rem" }}>Dashboard</h1>
          <p className="text-caption" style={{ marginTop: "var(--space-1)" }}>
            Aggregate metrics across all eval calls
          </p>
        </div>
        <Link href="/evals" style={{ textDecoration: "none" }}>
          <Button variant="primary">
            <FlaskConical size={14} strokeWidth={ICON_STROKE} />Run Eval
          </Button>
        </Link>
      </div>

      {loading && (
        <div className="placeholder" style={{ minHeight: 200 }}>
          <span className="spinner" />Loading metrics…
        </div>
      )}
      {error && (
        <div className="status err" style={{ marginBottom: "var(--space-5)" }}>
          ⚠ {error} — is evalra_backend running on port 8100?
        </div>
      )}

      {summary && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "var(--space-4)", marginBottom: "var(--space-5)" }}>
            <KpiCard icon={PhoneCall} label="Total calls" value={String(summary.n)} sub="all time" />
            <KpiCard icon={TrendingUp} label="Connection rate" value={pct(summary.connection_success_rate)} sub="calls that connected" />
            <KpiCard icon={XCircle} label="Drop rate" value={pct(summary.mid_call_drop_rate)} sub="mid-call disconnects" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "var(--space-4)", marginBottom: "var(--space-5)" }}>
            <div className="panel">
              <SectionHead icon={Zap} title="End-to-End Response Latency" />
              <p className="text-caption" style={{ marginBottom: "var(--space-2)" }}>
                {summary.latency_scope === "all" ? "All connected calls" : "Normal factual query"}
                {summary.baseline_n > 0 ? ` · ${summary.baseline_n} call${summary.baseline_n === 1 ? "" : "s"}` : ""}
              </p>
              <MetricRow label="Average" value={ms(summary.baseline_agent_latency_avg_s)} />
              <MetricRow label="Median (P50)" value={ms(summary.baseline_agent_latency_p50_s)} />
              <MetricRow label="P99" value={ms(summary.baseline_agent_latency_p99_s)} />
            </div>

            <div className="panel">
              <SectionHead icon={Radio} title="Interruption Handling" />
              <MetricRow label="Detection accuracy" sub="real barge-in vs noise" value={pct(summary.avg_interruption_detection_accuracy)} />
              <MetricRow label="Agent talk → interrupt" sub="avg delay into turn" value={ms(summary.avg_barge_in_agent_talk_to_interruption_avg_s)} />
              <MetricRow label="Interrupt → stop" sub="avg response latency" value={ms(summary.avg_interruption_response_latency_avg_s)} />
              <MetricRow label="False interruption rate" sub="noise triggered" value={pct(summary.avg_false_interruption_rate)} />
            </div>

            <div className="panel">
              <SectionHead icon={Star} title="Reliability & Quality" />
              <MetricRow label="Graceful termination" value={pct(summary.graceful_termination_rate)} />
              <MetricRow label="Dead air rate" sub="incidents / min" value={summary.avg_dead_air_rate_per_min !== null ? `${fmt(summary.avg_dead_air_rate_per_min, 2)}/min` : "—"} />
              <MetricRow label="Avg duration" value={summary.avg_duration_secs !== null ? `${fmt(summary.avg_duration_secs, 0)}s` : "—"} />
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "var(--space-4)", marginBottom: "var(--space-5)" }}>
            <div className="panel">
              <SectionHead icon={PhoneCall} title="Outcome breakdown" />
              {chartData.length === 0 ? (
                <p className="text-caption">No data yet</p>
              ) : (
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={chartData} barSize={28}>
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: "var(--fill-secondary)" }} contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--border)" }} />
                    <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                      {chartData.map((entry, i) => <Cell key={i} fill={entry.color} fillOpacity={0.85} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="panel">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-4)" }}>
                <SectionHead icon={Timer} title="Recent calls" />
                <Link href="/reports" className="call-list__link" style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-1)" }}>
                  All reports <ArrowRight size={12} />
                </Link>
              </div>
              {recent.length === 0 ? (
                <p className="text-caption">No calls yet — run your first eval.</p>
              ) : (
                <div>
                  <div className="call-list__head">
                    <span>Time</span>
                    <span>Number</span>
                    <span>Result</span>
                    <span>Duration</span>
                    <span />
                  </div>
                  <div className="call-list">
                    {recent.map((c) => (
                      <div key={c.call_id} className="call-list__row">
                        <span className="call-list__time">
                          {new Date(c.generated_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                        </span>
                        <span className="call-list__number">{c.voicera_number}</span>
                        <span><EvalResultPill result={c.eval_result} /></span>
                        <span className="call-list__time">
                          {c.duration_secs !== null && c.duration_secs !== undefined ? `${Math.round(c.duration_secs)}s` : "—"}
                        </span>
                        <Link href={`/reports/${c.call_id}`} className="call-list__link">View →</Link>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
