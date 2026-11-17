"use client";

import { useEffect, useState } from "react";
import {
  Activity, Plus, Trash2, ChevronDown, ChevronUp, Clock, History, X,
} from "lucide-react";
import { Button, Card, SegmentedControl, Switch, Stepper } from "../../components/ui";
import { ICON_SIZE, ICON_STROKE } from "../../lib/icons";
import { EvalResultPill } from "../../lib/evalResult";

const API = process.env.NEXT_PUBLIC_EVALRA_API || "http://localhost:8100";

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("evalra_token") : null;
  return { ...extra, ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

const INTERVAL_OPTIONS = [
  { value: "15", label: "15m" },
  { value: "30", label: "30m" },
  { value: "60", label: "1h" },
  { value: "360", label: "6h" },
  { value: "1440", label: "24h" },
];

const EVAL_OPTIONS = [
  { value: "basic", label: "Basic" },
  { value: "standard", label: "Standard" },
  { value: "full", label: "Full" },
];

interface Pulse {
  id: string;
  name: string;
  voicera_number: string;
  objective: string | null;
  persona: string | null;
  evals: string;
  simulations: Record<string, any>;
  interval_minutes: number;
  max_runs: number | null;
  run_count: number;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_result: { status: string; call_id?: string; detail?: string } | null;
}

interface RunRow {
  call_id: string;
  generated_at: string;
  outcome: string;
  eval_result: string | null;
  csat: number | null;
}

function intervalLabel(mins: number) {
  return INTERVAL_OPTIONS.find((o) => Number(o.value) === mins)?.label || `${mins}m`;
}

function relativeTime(iso: string | null) {
  if (!iso) return "—";
  const diffMs = new Date(iso).getTime() - Date.now();
  const mins = Math.round(diffMs / 60000);
  if (Math.abs(mins) < 1) return "just now";
  if (mins > 0) return `in ${mins < 60 ? `${mins}m` : `${Math.round(mins / 60)}h`}`;
  const ago = -mins;
  return `${ago < 60 ? `${ago}m` : `${Math.round(ago / 60)}h`} ago`;
}

function ResultBadge({ result }: { result: Pulse["last_result"] }) {
  if (!result) return <span className="badge neutral">No runs yet</span>;
  if (result.status === "started") return <span className="badge ok">Started</span>;
  return <span className="badge bad">Failed</span>;
}

function RunProgress({ pulse }: { pulse: Pulse }) {
  if (!pulse.max_runs) {
    return <span className="pulse-progress">{pulse.run_count} runs · ∞</span>;
  }
  const pct = Math.min(100, Math.round((pulse.run_count / pulse.max_runs) * 100));
  return (
    <span className="pulse-progress">
      {pulse.run_count}/{pulse.max_runs}
      <span className="pulse-progress__bar">
        <span className="pulse-progress__fill" style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

export default function PulsePage() {
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, RunRow[]>>({});

  const [name, setName] = useState("");
  const [voiceraNumber, setVoiceraNumber] = useState("");
  const [objective, setObjective] = useState("");
  const [persona, setPersona] = useState("");
  const [interval, setInterval_] = useState("60");
  const [evalsPreset, setEvalsPreset] = useState("standard");
  const [ambientNoise, setAmbientNoise] = useState(false);
  const [bargeIn, setBargeIn] = useState(false);
  const [limitRuns, setLimitRuns] = useState(false);
  const [maxRuns, setMaxRuns] = useState(10);

  async function loadPulses() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/pulses`, { headers: authHeaders() });
      if (!res.ok) throw new Error("Failed to load pulses");
      setPulses(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load pulses");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPulses();
  }, []);

  function resetForm() {
    setName(""); setVoiceraNumber(""); setObjective(""); setPersona("");
    setAmbientNoise(false); setBargeIn(false); setInterval_("60"); setEvalsPreset("standard");
    setLimitRuns(false); setMaxRuns(10);
  }

  async function createPulse(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !voiceraNumber.trim()) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${API}/pulses`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          name,
          voicera_number: voiceraNumber,
          objective: objective || null,
          persona: persona || null,
          evals: evalsPreset,
          interval_minutes: Number(interval),
          max_runs: limitRuns ? maxRuns : null,
          simulations: {
            ambient_noise: { enabled: ambientNoise },
            barge_in: { enabled: bargeIn },
          },
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to create pulse");
      resetForm();
      setFormOpen(false);
      await loadPulses();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create pulse");
    } finally {
      setSaving(false);
    }
  }

  async function toggleEnabled(pulse: Pulse) {
    setPulses((prev) => prev.map((p) => (p.id === pulse.id ? { ...p, enabled: !p.enabled } : p)));
    await fetch(`${API}/pulses/${pulse.id}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ enabled: !pulse.enabled }),
    });
    loadPulses();
  }

  async function deletePulse(id: string) {
    setPulses((prev) => prev.filter((p) => p.id !== id));
    await fetch(`${API}/pulses/${id}`, { method: "DELETE", headers: authHeaders() });
  }

  async function toggleExpand(pulse: Pulse) {
    if (expanded === pulse.id) {
      setExpanded(null);
      return;
    }
    setExpanded(pulse.id);
    if (!runs[pulse.id]) {
      const res = await fetch(`${API}/pulses/${pulse.id}/runs`, { headers: authHeaders() });
      if (res.ok) {
        const data: RunRow[] = await res.json();
        setRuns((prev) => ({ ...prev, [pulse.id]: data }));
      }
    }
  }

  return (
    <div className="page-container">
      <div className="pulse-header">
        <div className="pulse-header__text">
          <div className="page-header__row">
            <Activity size={ICON_SIZE} strokeWidth={ICON_STROKE} />
            <h1 className="page-title">Pulse</h1>
          </div>
          <p className="page-subtitle">
            Recurring eval tests fired on a schedule — a heartbeat check for your voice agent between manual runs.
          </p>
        </div>
        <Button variant="primary" onClick={() => setFormOpen((v) => !v)}>
          {formOpen ? <X size={14} strokeWidth={ICON_STROKE} /> : <Plus size={14} strokeWidth={ICON_STROKE} />}
          {formOpen ? "Close" : "New pulse"}
        </Button>
      </div>

      {formOpen && (
        <Card className="pulse-form-card" padding="lg">
          <form onSubmit={createPulse} style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
            <h2 className="pulse-form-title">Configure a new pulse</h2>

            <div className="pulse-form-grid">
              <div className="pulse-field">
                <label className="text-label">Name</label>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Hourly order-status check" required />
              </div>
              <div className="pulse-field">
                <label className="text-label">Agent number</label>
                <input value={voiceraNumber} onChange={(e) => setVoiceraNumber(e.target.value)} placeholder="+91 9876543210" required />
              </div>
              <div className="pulse-field pulse-form-grid--full">
                <label className="text-label">Objective</label>
                <input value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="Find out the status of a recent order" />
              </div>
              <div className="pulse-field pulse-form-grid--full">
                <label className="text-label">Persona (optional)</label>
                <input value={persona} onChange={(e) => setPersona(e.target.value)} placeholder="An impatient customer" />
              </div>
            </div>

            <div className="pulse-form-section">
              <div>
                <label className="text-label">Run every</label>
                <SegmentedControl options={INTERVAL_OPTIONS} value={interval} onChange={setInterval_} />
              </div>
              <div>
                <label className="text-label">Eval depth</label>
                <SegmentedControl options={EVAL_OPTIONS} value={evalsPreset} onChange={setEvalsPreset} />
              </div>
              <div className="pulse-limit-row">
                <Switch checked={limitRuns} onChange={setLimitRuns} label="Stop after a number of runs" sub="Leave off to run indefinitely on this interval" />
                {limitRuns && (
                  <div className="pulse-limit-row__stepper">
                    runs
                    <Stepper value={maxRuns} onDec={() => setMaxRuns((n) => Math.max(1, n - 1))} onInc={() => setMaxRuns((n) => n + 1)} min={1} active />
                  </div>
                )}
              </div>
            </div>

            <div className="pulse-form-section">
              <label className="text-label" style={{ marginBottom: 0 }}>Simulations</label>
              <div className="ui-inset-list">
                <Switch checked={ambientNoise} onChange={setAmbientNoise} label="Ambient noise" sub="Mix background café/office noise into the call" />
                <Switch checked={bargeIn} onChange={setBargeIn} label="Barge-in" sub="Interrupt the agent mid-turn to test recovery" />
              </div>
            </div>

            <div className="pulse-form-actions">
              <Button type="submit" variant="primary" disabled={saving}>
                {saving ? "Creating…" : "Create pulse"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => { setFormOpen(false); resetForm(); }}>Cancel</Button>
            </div>
          </form>
        </Card>
      )}

      {error && <p className="form-error">{error}</p>}

      {loading ? (
        <p className="text-caption">Loading pulses…</p>
      ) : pulses.length === 0 ? (
        <div className="pulse-empty">
          <div className="pulse-empty__icon"><Activity size={20} strokeWidth={ICON_STROKE} /></div>
          <p className="text-body" style={{ fontWeight: 600 }}>No pulses configured yet</p>
          <p className="text-caption">Create one to start a recurring check-up on your agent.</p>
        </div>
      ) : (
        <div className="pulse-list">
          {pulses.map((pulse) => (
            <Card key={pulse.id} className={`pulse-card${pulse.enabled ? "" : " pulse-card--disabled"}`}>
              <div className="pulse-card__head">
                <div className="pulse-card__title-wrap">
                  <span className={`pulse-dot${pulse.enabled ? " pulse-dot--on" : ""}`} />
                  <div style={{ minWidth: 0 }}>
                    <div className="pulse-card__title">{pulse.name}</div>
                    <div className="pulse-card__sub">
                      <span className="meta-chip">{intervalLabel(pulse.interval_minutes)}</span>
                      <span className="call-list__number">{pulse.voicera_number}</span>
                      {pulse.objective && <span className="pulse-card__objective">{pulse.objective}</span>}
                    </div>
                  </div>
                </div>
                <div className="pulse-card__actions">
                  <RunProgress pulse={pulse} />
                  <ResultBadge result={pulse.last_result} />
                  <Switch checked={pulse.enabled} onChange={() => toggleEnabled(pulse)} />
                  <button className="icon-btn" onClick={() => deletePulse(pulse.id)} aria-label="Delete pulse">
                    <Trash2 size={15} strokeWidth={ICON_STROKE} />
                  </button>
                </div>
              </div>
              <div className="pulse-card__meta">
                <span className="pulse-card__meta-item"><Clock size={12} /> Next {relativeTime(pulse.next_run_at)}</span>
                <span className="pulse-card__meta-item"><History size={12} /> Last {relativeTime(pulse.last_run_at)}</span>
                <button className="pulse-card__expand" onClick={() => toggleExpand(pulse)}>
                  History {expanded === pulse.id ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
              </div>
              {expanded === pulse.id && (
                <div className="call-list">
                  {(runs[pulse.id] || []).length === 0 ? (
                    <div className="reports-empty">No runs recorded yet.</div>
                  ) : (
                    (runs[pulse.id] || []).map((r) => (
                      <a key={r.call_id} href={`/reports/${r.call_id}`} className="call-list__row">
                        <span className="call-list__time">{new Date(r.generated_at).toLocaleString()}</span>
                        <span><EvalResultPill result={r.eval_result} /></span>
                        <span>{r.csat ?? "—"}</span>
                        <span className="call-list__link">View →</span>
                      </a>
                    ))
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
