"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  ChevronLeft, ChevronRight,
  X, Play, ArrowRight, ArrowLeft, Plus, CheckCircle2, Maximize2,
} from "lucide-react";
import Report from "./Report";
import BatchReport from "./BatchReport";
import { ReportData } from "../../lib/types";
import { Button } from "../../components/ui";
import { InsetList, InsetRow } from "../../components/ui/InsetList";
import { ICON_SIZE, ICON_STROKE } from "../../lib/icons";
import StepBar from "./components/StepBar";
import SimulationSidebar from "./components/SimulationSidebar";
import { SIM_META, type SimCounts, type SimType } from "./components/simTypes";
import AmbientNoisePicker, { type AmbientNoiseConfig, type NoiseType, NOISE_PREVIEW_SECS } from "./components/AmbientNoisePicker";
import BargeInOptions, { type BargeInConfig, type FillerPreset } from "./components/BargeInOptions";
import ObjectiveEditorModal from "./components/ObjectiveEditorModal";
import { FALLBACK_INTERRUPTION_PRESETS, FALLBACK_NOISE_PRESETS, INTERRUPTION_PREVIEW_SECS } from "./components/constants";
import type { InterruptionPreset } from "./components/InterruptionSoundPicker";
import { evalsAuthHeaders, fetchAudioBlobUrl } from "../../lib/evalsApi";

export type { SimType } from "./components/simTypes";

export type CallState = { id: string; report: ReportData | null; simType: SimType };

const API = process.env.NEXT_PUBLIC_EVALS_API || "http://localhost:7870";

const EVAL_PRESETS = ["basic", "standard", "full"];

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "hi", label: "Hindi" },
  { code: "mr", label: "Marathi" },
  { code: "bn", label: "Bengali" },
  { code: "te", label: "Telugu" },
  { code: "ta", label: "Tamil" },
  { code: "gu", label: "Gujarati" },
  { code: "kn", label: "Kannada" },
  { code: "ml", label: "Malayalam" },
  { code: "pa", label: "Punjabi" },
  { code: "or", label: "Odia" },
  { code: "as", label: "Assamese" },
  { code: "ur", label: "Urdu" },
  { code: "ne", label: "Nepali" },
  { code: "si", label: "Sinhala" },
  { code: "kok", label: "Konkani" },
  { code: "mai", label: "Maithili" },
  { code: "bho", label: "Bhojpuri" },
  { code: "raj", label: "Rajasthani" },
];

const LANGUAGE_NUMBERS: Record<string, { label: string; number: string }[]> = {
  en: [{ label: "English agent  ", number: "" }],
  mr: [{ label: "Marathi agent  ", number: "" }],
};

// ── Personas ──────────────────────────────────────────────────────────────────

type Persona = { id: string; name: string; desc: string; emoji: string; prompt: string };

const PERSONAS: Persona[] = [
  { id: "sarah", name: "Sarah", desc: "In a hurry", emoji: "⚡",
    prompt: "You are Sarah, a busy professional in a hurry. Speak quickly and get to the point. Show mild impatience if the agent is slow." },
  { id: "rohan", name: "Rohan", desc: "Confused", emoji: "🤔",
    prompt: "You are Rohan, a confused customer unsure what you need. Ask clarifying questions, occasionally repeat yourself." },
  { id: "arun", name: "Arun", desc: "Elderly", emoji: "🧓",
    prompt: "You are Arun, an elderly customer who speaks slowly and may ask the agent to repeat themselves. Speak formally." },
  { id: "maya", name: "Maya", desc: "Expert user", emoji: "🎯",
    prompt: "You are Maya, a technical expert who knows exactly what you want. Expect precise answers and challenge vague responses." },
  { id: "dev", name: "Dev", desc: "Skeptical", emoji: "🧐",
    prompt: "You are Dev, a skeptical customer who questions everything. Push for concrete evidence and verification." },
  { id: "priya", name: "Priya", desc: "Frustrated", emoji: "😤",
    prompt: "You are Priya, a frustrated customer who has already tried to resolve this issue multiple times. Show clear urgency." },
];

const PERSONA_MAP = Object.fromEntries(PERSONAS.map((p) => [p.id, p.prompt]));

// ── Simulation types ──────────────────────────────────────────────────────────

type LangSwitchStep = { switch_to: string; after_turn: number };

const DEFAULT_AMBIENT_NOISE: AmbientNoiseConfig = { type: "cafe", volume: 0.15 };
const DEFAULT_BARGE_IN: BargeInConfig = {
  real_count: 1,
  after_secs: 2,
  style: "speech",
  sound_type: "trucksounds",
  sound_volume: 0.20,
  fake_count: 0,
  fake_burst_secs: 2,
  fake_volume: 0.8,
  cough_enabled: false,
  hmm_enabled: false,
  filler_volume: 0.5,
  probe_stop_enabled: true,
  probe_start_enabled: true,
  enabled_custom_reactions: [],
};
type SimConfigs = {
  ambient_noise:   AmbientNoiseConfig;
  barge_in:        BargeInConfig;
  language_switch: { sequence: LangSwitchStep[]; voicera_response_language: string };
};

const DEFAULT_CONFIGS: SimConfigs = {
  ambient_noise:   DEFAULT_AMBIENT_NOISE,
  barge_in:        DEFAULT_BARGE_IN,
  language_switch: { sequence: [{ switch_to: "hi", after_turn: 1 }], voicera_response_language: "" },
};

type QueueEntry = {
  id: string; simType: SimType;
  language: string; agentNumber: string;
  objective: string; expectedOutcome: string; personaId: string;
  ambientNoise: AmbientNoiseConfig;
  bargeIn: BargeInConfig;
};

type Phase = "idle" | "calling" | "waiting" | "ready" | "error";

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Home() {
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [evals, setEvals] = useState("standard");
  const [maxMinutes, setMaxMinutes] = useState(3);

  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [simConfigs, setSimConfigs] = useState<SimConfigs>(DEFAULT_CONFIGS);
  const [selectedSim, setSelectedSim] = useState<SimType>("baseline");
  const [callIndex, setCallIndex] = useState(0);

  const [phase, setPhase] = useState<Phase>("idle");
  const [calls, setCalls] = useState<CallState[]>([]);
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0 });
  const [error, setError] = useState("");
  const abortRef = useRef(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewBlobRef = useRef<string | null>(null);
  const [previewingKey, setPreviewingKey] = useState<string | null>(null);
  const [noisePresets, setNoisePresets] = useState(FALLBACK_NOISE_PRESETS);
  const [interruptionPresets, setInterruptionPresets] = useState<InterruptionPreset[]>(FALLBACK_INTERRUPTION_PRESETS);
  const [fillerPresets, setFillerPresets] = useState<FillerPreset[]>([
    { id: "cough", label: "Cough" },
    { id: "hmm", label: "Hmm" },
  ]);
  const [objectiveModalEntryId, setObjectiveModalEntryId] = useState<string | null>(null);
  const objectiveModalEntry = useMemo(
    () => queue.find((e) => e.id === objectiveModalEntryId) ?? null,
    [queue, objectiveModalEntryId],
  );

  function stopNoisePreview() {
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.currentTime = 0;
      previewAudioRef.current = null;
    }
    if (previewBlobRef.current) {
      URL.revokeObjectURL(previewBlobRef.current);
      previewBlobRef.current = null;
    }
    setPreviewingKey(null);
  }

  async function startPreview(
    key: string,
    endpoint: string,
    volume: number,
    durationSecs: number,
    needsAuth = false,
  ) {
    if (previewingKey === key) {
      stopNoisePreview();
      return;
    }
    stopNoisePreview();
    try {
      const url = needsAuth
        ? await fetchAudioBlobUrl(endpoint)
        : `${API}${endpoint}`;
      if (needsAuth) previewBlobRef.current = url;
      const audio = new Audio(url);
      audio.volume = volume;
      previewAudioRef.current = audio;
      setPreviewingKey(key);
      audio.play().catch(() => stopNoisePreview());
      previewTimerRef.current = setTimeout(stopNoisePreview, durationSecs * 1000);
    } catch {
      stopNoisePreview();
    }
  }

  function previewNoise(id: NoiseType, volume: number, previewKey: string) {
    const key = `${previewKey}:${id}`;
    void startPreview(
      key,
      `/api/noise-preview/${id}`,
      volume,
      NOISE_PREVIEW_SECS,
      id.startsWith("lib_"),
    );
  }

  function previewInterruption(id: string, previewKey: string, volume: number) {
    const key = `int:${previewKey}:${id}`;
    void startPreview(
      key,
      `/api/interruption-preview/${id}`,
      volume,
      INTERRUPTION_PREVIEW_SECS,
      id.startsWith("lib_"),
    );
  }

  function previewFiller(id: string, previewKey: string, volume: number) {
    const key = `filler:${previewKey}:${id}`;
    void startPreview(
      key,
      `/api/filler-preview/${id}`,
      volume,
      INTERRUPTION_PREVIEW_SECS,
      id.startsWith("lib_"),
    );
  }
  useEffect(() => {
    const headers = evalsAuthHeaders();
    Promise.all([
      fetch(`${API}/api/noise-presets`, { headers }).then((r) => (r.ok ? r.json() : null)),
      fetch(`${API}/api/interruption-presets`, { headers }).then((r) => (r.ok ? r.json() : null)),
      fetch(`${API}/api/filler-presets`, { headers }).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([noise, interruption, filler]) => {
        if (noise?.presets?.length) setNoisePresets(noise.presets);
        if (interruption?.presets?.length) setInterruptionPresets(interruption.presets);
        if (filler?.presets?.length) setFillerPresets(filler.presets);
      })
      .catch(() => {});
  }, []);

  useEffect(() => () => {
    abortRef.current = true;
    if (pollRef.current) clearInterval(pollRef.current);
    if (previewTimerRef.current) clearTimeout(previewTimerRef.current);
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current = null;
    }
    if (previewBlobRef.current) {
      URL.revokeObjectURL(previewBlobRef.current);
      previewBlobRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!previewingKey || !previewAudioRef.current) return;
    if (previewingKey.startsWith("filler:")) {
      const parts = previewingKey.split(":");
      const previewScope = parts[1];
      const volume = previewScope === "default"
        ? simConfigs.barge_in.filler_volume
        : queue.find((e) => e.id === previewScope)?.bargeIn.filler_volume ?? 0.5;
      previewAudioRef.current.volume = volume;
      return;
    }
    if (previewingKey.startsWith("int:")) {
      const previewScope = previewingKey.split(":")[1];
      const volume = previewScope === "default"
        ? simConfigs.barge_in.sound_volume
        : queue.find((e) => e.id === previewScope)?.bargeIn.sound_volume ?? 0.8;
      previewAudioRef.current.volume = volume;
      return;
    }
    const [previewScope] = previewingKey.split(":");
    if (previewScope === "default") {
      previewAudioRef.current.volume = simConfigs.ambient_noise.volume;
      return;
    }
    const entry = queue.find((e) => e.id === previewScope);
    if (entry) previewAudioRef.current.volume = entry.ambientNoise.volume;
  }, [queue, simConfigs.ambient_noise.volume, simConfigs.barge_in.sound_volume, simConfigs.barge_in.filler_volume, previewingKey]);

  useEffect(() => {
    if (step === 1 && queue.length === 0) setStep(0);
    setCallIndex((i) => Math.min(i, Math.max(0, queue.length - 1)));
  }, [queue.length, step]);

  function goToCall(index: number) {
    stopNoisePreview();
    setCallIndex(index);
  }

  function addCall(simType: SimType) {
    setQueue((p) => [...p, {
      id: crypto.randomUUID(), simType,
      language: "en", agentNumber: LANGUAGE_NUMBERS.en[0].number,
      objective: "", expectedOutcome: "", personaId: "",
      ambientNoise: { ...simConfigs.ambient_noise },
      bargeIn: { ...simConfigs.barge_in },
    }]);
    if (simType !== "baseline") setSelectedSim(simType);
  }

  const simCounts = useMemo<SimCounts>(() => {
    const c: SimCounts = { baseline: 0, ambient_noise: 0, barge_in: 0, language_switch: 0 };
    queue.forEach((e) => c[e.simType]++);
    return c;
  }, [queue]);

  function removeLastOfType(simType: SimType) {
    setQueue((p) => {
      const idx = [...p].map((e, i) => ({ e, i })).filter(({ e }) => e.simType === simType).pop()?.i;
      return idx !== undefined ? p.filter((_, i) => i !== idx) : p;
    });
  }

  function removeEntry(id: string) {
    setQueue((p) => {
      const entry = p.find((e) => e.id === id);
      const remaining = p.filter((e) => e.id !== id);
      if (entry && !remaining.some((e) => e.simType === entry.simType) && selectedSim === entry.simType) {
        setSelectedSim("baseline");
      }
      return remaining;
    });
  }

  function patchEntry(id: string, patch: Partial<Omit<QueueEntry, "id">>) {
    setQueue((p) => p.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  }

  function patchConfig<K extends keyof SimConfigs>(key: K, patch: Partial<SimConfigs[K]>) {
    setSimConfigs((p) => ({ ...p, [key]: { ...p[key], ...patch } }));
  }

  function buildBodyForEntry(entry: QueueEntry): Record<string, unknown> {
    const personaText = PERSONA_MAP[entry.personaId] ?? "";
    const sims = {
      ambient_noise:   { enabled: entry.simType === "ambient_noise",   ...entry.ambientNoise },
      barge_in:        { enabled: entry.simType === "barge_in",        ...entry.bargeIn },
      language_switch: { enabled: entry.simType === "language_switch", sequence: simConfigs.language_switch.sequence },
    };
    const body: Record<string, unknown> = {
      voicera_number: entry.agentNumber.trim(),
      evals,
      language: entry.language,
      max_duration_minutes: Number(maxMinutes),
      simulations: sims,
    };
    if (entry.objective.trim()) body.objective = entry.objective.trim();
    if (entry.expectedOutcome.trim()) body.expected_outcome = entry.expectedOutcome.trim();
    if (personaText) body.persona = personaText;
    if (entry.simType === "barge_in") body.barge_in_style = entry.bargeIn.style;
    if (simConfigs.language_switch.voicera_response_language)
      body.voicera_response_language = simConfigs.language_switch.voicera_response_language;
    return body;
  }

  async function startOneCall(body: Record<string, unknown>): Promise<string> {
    const token = typeof window !== "undefined" ? localStorage.getItem("evalra_token") : null;
    const res = await fetch(`${API}/api/evals-call`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    return data.call_id as string;
  }

  function waitForReport(id: string, deadlineMs: number): Promise<ReportData> {
    return new Promise((resolve, reject) => {
      const iv = setInterval(async () => {
        if (abortRef.current) { clearInterval(iv); reject(new Error("aborted")); return; }
        if (Date.now() > deadlineMs) { clearInterval(iv); reject(new Error("timeout waiting for report")); return; }
        try {
          const r = await fetch(`${API}/api/report/${id}/status`);
          const d = await r.json();
          if (d.ready) {
            clearInterval(iv);
            const rep = await fetch(`${API}/api/report/${id}`);
            resolve(await rep.json());
          }
        } catch { /* keep polling */ }
      }, 4000);
      pollRef.current = iv;
    });
  }

  async function submit() {
    if (queue.length === 0 || busy) return;
    if (pollRef.current) clearInterval(pollRef.current);
    abortRef.current = false;
    setError("");
    setCalls([]);
    setBatchProgress({ current: 0, total: queue.length });
    setStep(2);

    const allCalls: CallState[] = [];
    const perCallDeadline = (Number(maxMinutes) * 60 + 180) * 1000;

    try {
      for (let i = 0; i < queue.length; i++) {
        if (abortRef.current) break;
        const entry = queue[i];
        setBatchProgress({ current: i + 1, total: queue.length });
        setPhase("calling");
        const id = await startOneCall(buildBodyForEntry(entry));
        allCalls.push({ id, report: null, simType: entry.simType });
        setCalls([...allCalls]);
        setPhase("waiting");
        const report = await waitForReport(id, Date.now() + perCallDeadline);
        allCalls[i] = { id, report, simType: entry.simType };
        setCalls([...allCalls]);
        if (i < queue.length - 1 && !abortRef.current) await new Promise((r) => setTimeout(r, 3000));
      }
      setPhase("ready");
    } catch (err) {
      if (!abortRef.current) { setError(err instanceof Error ? err.message : String(err)); setPhase("error"); }
    }
  }

  const busy = phase === "calling" || phase === "waiting";

  function startOver() {
    abortRef.current = true;
    if (pollRef.current) clearInterval(pollRef.current);
    setPhase("idle");
    setCalls([]);
    setError("");
    setQueue([]);
    setSelectedSim("baseline");
    setStep(0);
  }

  return (
    <div className="page-container">

      <StepBar current={step} />

      {/* ── Step 0: Pick simulations ── */}
      {step === 0 && (
        <div className="evals-step0-layout">
          <SimulationSidebar
            selectedSim={selectedSim}
            simCounts={simCounts}
            onSelect={setSelectedSim}
            onInc={addCall}
            onDec={removeLastOfType}
            evalPresets={EVAL_PRESETS}
            evals={evals}
            onEvalsChange={setEvals}
            maxMinutes={maxMinutes}
            onMaxMinutesChange={setMaxMinutes}
            advancedOpen={advancedOpen}
            onAdvancedToggle={() => setAdvancedOpen((v) => !v)}
          />

          <div className="card evals-step0-panel">
            <div style={{ marginBottom: "var(--space-5)" }}>
              <h2 className="text-heading">Pick simulations</h2>
              <p className="text-caption" style={{ marginTop: "var(--space-1)" }}>
                Choose which scenarios to test and how many calls each.
              </p>
            </div>

            <div className="sim-picker__main">
              {simCounts[selectedSim] === 0 ? (
                <div className="sim-picker__empty">
                  <div className="sim-picker__empty-icon">
                    <Plus size={20} strokeWidth={ICON_STROKE} />
                  </div>
                  <p className="text-label" style={{ margin: 0 }}>
                    Add {SIM_META[selectedSim].label.toLowerCase()} calls
                  </p>
                  <p className="text-caption" style={{ margin: 0, maxWidth: 280 }}>
                    Use the + control in the sidebar to queue calls for this simulation.
                  </p>
                </div>
              ) : (
                <>
                  <div className="sim-picker__main-header">
                    <h3 className="sim-picker__main-title">{SIM_META[selectedSim].label}</h3>
                    <p className="sim-picker__main-desc">{SIM_META[selectedSim].desc}</p>
                  </div>
                  <div className="sim-picker__main-content">
                    {selectedSim === "baseline" && (
                      <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "flex-start" }}>
                        <CheckCircle2 size={18} strokeWidth={ICON_STROKE} color="var(--accent)" style={{ flexShrink: 0, marginTop: 2 }} />
                        <p className="text-caption" style={{ margin: 0 }}>
                          Baseline calls run without injected simulations. You&apos;ll set language, objective, and persona in the next step.
                        </p>
                      </div>
                    )}

                    {selectedSim === "ambient_noise" && (
                      <>
                        <p className="text-caption">
                          Default for new ambient-noise calls. Override sound and volume per call in the next step.
                        </p>
                        <AmbientNoisePicker
                          presets={noisePresets}
                          config={simConfigs.ambient_noise}
                          previewKey="default"
                          previewingKey={previewingKey}
                          onChange={(patch) => patchConfig("ambient_noise", patch)}
                          onPreview={previewNoise}
                        />
                      </>
                    )}

                    {selectedSim === "barge_in" && (
                      <>
                        <p className="text-caption">
                          Default for new barge-in calls. Override per call in the next step.
                        </p>
                        <BargeInOptions
                          config={simConfigs.barge_in}
                          presets={interruptionPresets}
                          customReactions={fillerPresets}
                          previewKey="default"
                          previewingKey={previewingKey}
                          onChange={(patch) => patchConfig("barge_in", patch)}
                          onPreviewInterruption={previewInterruption}
                          onPreviewFiller={previewFiller}
                        />
                      </>
                    )}

                    {selectedSim === "language_switch" && (
                      <>
                        <p className="text-label">Agent responds in</p>
                        <select
                          value={simConfigs.language_switch.voicera_response_language}
                          onChange={(e) => patchConfig("language_switch", { voicera_response_language: e.target.value })}
                        >
                          <option value="">Same as tester language</option>
                          {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                        </select>
                        <p className="text-caption" style={{ marginTop: "var(--space-1)", marginBottom: "var(--space-4)" }}>
                          Keeps this language in the STT after each switch so the agent&apos;s responses stay audible.
                        </p>

                        <p className="text-label">Switch sequence</p>
                        <InsetList>
                          {simConfigs.language_switch.sequence.map((seqStep, i) => (
                            <InsetRow key={i}>
                              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", width: "100%" }}>
                                <span className="text-caption" style={{ fontWeight: 600, minWidth: 24 }}>#{i + 1}</span>
                                <select
                                  value={seqStep.switch_to}
                                  onChange={(e) => {
                                    const seq = simConfigs.language_switch.sequence.map((s, j) =>
                                      j === i ? { ...s, switch_to: e.target.value } : s
                                    );
                                    patchConfig("language_switch", { sequence: seq });
                                  }}
                                  style={{ flex: 1 }}
                                >
                                  {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                                </select>
                                <span className="text-caption" style={{ whiteSpace: "nowrap" }}>after turn</span>
                                <input
                                  type="number"
                                  min={1}
                                  max={10}
                                  value={seqStep.after_turn}
                                  onChange={(e) => {
                                    const seq = simConfigs.language_switch.sequence.map((s, j) =>
                                      j === i ? { ...s, after_turn: Number(e.target.value) } : s
                                    );
                                    patchConfig("language_switch", { sequence: seq });
                                  }}
                                  style={{ width: 48, textAlign: "center" }}
                                />
                                <button
                                  type="button"
                                  onClick={() =>
                                    patchConfig("language_switch", {
                                      sequence: simConfigs.language_switch.sequence.filter((_, j) => j !== i),
                                    })
                                  }
                                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", padding: 0, display: "flex" }}
                                >
                                  <X size={14} />
                                </button>
                              </div>
                            </InsetRow>
                          ))}
                        </InsetList>
                        <Button
                          variant="ghost"
                          size="sm"
                          style={{ marginTop: "var(--space-2)", width: "100%" }}
                          onClick={() => {
                            const last = simConfigs.language_switch.sequence.at(-1);
                            const nextTurn = last ? last.after_turn + 1 : 1;
                            patchConfig("language_switch", {
                              sequence: [...simConfigs.language_switch.sequence, { switch_to: "mr", after_turn: nextTurn }],
                            });
                          }}
                        >
                          + Add switch
                        </Button>
                      </>
                    )}
                  </div>
                </>
              )}
            </div>

          <Button
            variant="primary"
            size="lg"
            fullWidth
            onClick={() => { setCallIndex(0); setStep(1); }}
            disabled={queue.length === 0}
            style={{ marginTop: "var(--space-5)" }}
          >
            {queue.length === 0 ? (
              "Add at least one simulation to continue"
            ) : (
              <>Next — configure {queue.length} call{queue.length !== 1 ? "s" : ""} <ArrowRight size={15} /></>
            )}
          </Button>
          </div>
        </div>
      )}

      {/* ── Step 1: Configure calls (carousel) ── */}
      {step === 1 && queue.length > 0 && (() => {
        const idx = Math.min(callIndex, queue.length - 1);
        const entry = queue[idx];
        const { Icon, label } = SIM_META[entry.simType];
        const entryNumbers = LANGUAGE_NUMBERS[entry.language];
        const atStart = idx === 0;
        const atEnd = idx === queue.length - 1;

        return (
        <div className="card">
          <div style={{ marginBottom: "var(--space-5)" }}>
            <h2 className="text-heading">Configure each call</h2>
            <p className="text-caption" style={{ marginTop: "var(--space-1)" }}>Set language, agent number, objective, persona, and simulation options for each call.</p>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}>
            <Button variant="secondary" size="sm" disabled={atStart} onClick={() => goToCall(idx - 1)}>
              <ChevronLeft size={16} /> Prev
            </Button>
            <div style={{ textAlign: "center", flex: 1 }}>
              <div className="text-label" style={{ margin: 0 }}>Call {idx + 1} of {queue.length}</div>
              <div className="carousel-dots">
                {queue.map((q, i) => (
                  <button
                    key={q.id}
                    type="button"
                    className={`carousel-dot${i === idx ? " carousel-dot--active" : ""}`}
                    onClick={() => goToCall(i)}
                    title={`Call ${i + 1}: ${SIM_META[q.simType].label}`}
                  />
                ))}
              </div>
            </div>
            <Button variant="secondary" size="sm" disabled={atEnd} onClick={() => goToCall(idx + 1)}>
              Next <ChevronRight size={16} />
            </Button>
          </div>

          <div className="grouped-list">
            <div className="sim-row sim-row--active">
              <div className="sim-row__icon-wrap">
                <Icon size={ICON_SIZE} strokeWidth={ICON_STROKE} />
              </div>
              <div className="sim-row__body">
                <div className="sim-row__label">{label}</div>
                {entry.simType === "ambient_noise" && (
                  <div className="sim-row__desc">
                    {noisePresets.find((p) => p.id === entry.ambientNoise.type)?.label ?? entry.ambientNoise.type}
                  </div>
                )}
                {entry.simType === "barge_in" && (entry.bargeIn.style === "sound" || entry.bargeIn.style === "both") && (
                  <div className="sim-row__desc">
                    {interruptionPresets.find((p) => p.id === entry.bargeIn.sound_type)?.label ?? entry.bargeIn.sound_type}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => removeEntry(entry.id)}
                className="sim-row__remove"
                aria-label="Remove call"
              >
                <X size={14} strokeWidth={ICON_STROKE} />
              </button>
            </div>
          </div>

          <div className="options-panel">
            <div className="options-panel__content">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                <div>
                  <p className="text-label">Language</p>
                  <select
                    value={entry.language}
                    onChange={(e) => {
                      const lang = e.target.value;
                      const nums = LANGUAGE_NUMBERS[lang];
                      patchEntry(entry.id, { language: lang, agentNumber: nums?.[0]?.number ?? "" });
                    }}
                  >
                    {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                  </select>
                </div>
                <div>
                  <p className="text-label">Agent number</p>
                  
                    <input
                      type="text"
                      value={entry.agentNumber}
                      onChange={(e) => patchEntry(entry.id, { agentNumber: e.target.value })}
                      placeholder="e.g. +918071387387"
                    />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                <div>
                  <label className="text-label" style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}>
                    Objective
                    <span
                      tabIndex={0}
                      style={{
                        display: "inline-block",
                        cursor: "pointer",
                        color: "#888",
                        borderBottom: "1px dotted #888",
                        fontSize: "1em",
                      }}
                      title="The 'Objective' defines what the simulated caller is trying to achieve in this call. It acts as the initial prompt or goal for the scenario."
                    >
                      &#9432;
                    </span>
                    <button
                      type="button"
                      className="cds-iconbtn"
                      style={{ width: 26, height: 26, marginLeft: "auto" }}
                      onClick={() => setObjectiveModalEntryId(entry.id)}
                      aria-label="Open objective in full screen"
                      title="Expand to full screen"
                    >
                      <Maximize2 size={14} strokeWidth={ICON_STROKE} />
                    </button>
                  </label>
                  <input
                    type="text"
                    value={entry.objective}
                    onChange={(e) => patchEntry(entry.id, { objective: e.target.value })}
                    placeholder="e.g. find out the weather"
                  />
                </div>
                <div>
                  <p className="text-label">Expected outcome</p>
                  <input
                    type="text"
                    value={entry.expectedOutcome}
                    onChange={(e) => patchEntry(entry.id, { expectedOutcome: e.target.value })}
                    placeholder="e.g. agent says 28°C"
                  />
                </div>
              </div>

              <div>
                <p className="text-label">Persona</p>
                <select value={entry.personaId} onChange={(e) => patchEntry(entry.id, { personaId: e.target.value })}>
                  <option value="">No persona</option>
                  {PERSONAS.map((p) => (
                    <option key={p.id} value={p.id}>{p.emoji} {p.name} — {p.desc}</option>
                  ))}
                </select>
              </div>

              {entry.simType === "ambient_noise" && (
                <div style={{ marginTop: "var(--space-2)" }}>
                  <p className="text-label">Background noise</p>
                  <AmbientNoisePicker
                    presets={noisePresets}
                    config={entry.ambientNoise}
                    previewKey={entry.id}
                    previewingKey={previewingKey}
                    onChange={(patch) => patchEntry(entry.id, { ambientNoise: { ...entry.ambientNoise, ...patch } })}
                    onPreview={previewNoise}
                  />
                </div>
              )}

              {entry.simType === "barge_in" && (
                <div style={{ marginTop: "var(--space-2)" }}>
                  <p className="text-label">Barge-in</p>
                  <BargeInOptions
                    config={entry.bargeIn}
                    presets={interruptionPresets}
                    customReactions={fillerPresets}
                    previewKey={entry.id}
                    previewingKey={previewingKey}
                    onChange={(patch) => patchEntry(entry.id, { bargeIn: { ...entry.bargeIn, ...patch } })}
                    onPreviewInterruption={previewInterruption}
                    onPreviewFiller={previewFiller}
                  />
                </div>
              )}
            </div>
          </div>

          <div style={{ display: "flex", gap: "var(--space-3)", marginTop: "var(--space-5)" }}>
            <Button variant="secondary" onClick={() => { stopNoisePreview(); setStep(0); }}>
              <ArrowLeft size={14} /> Back
            </Button>
            <Button variant="primary" size="lg" onClick={submit} disabled={busy} style={{ flex: 1 }}>
              <Play size={14} strokeWidth={ICON_STROKE} /> Start eval — {queue.length} call{queue.length !== 1 ? "s" : ""} sequentially
            </Button>
          </div>
        </div>
        );
      })()}

      {/* ── Step 2: Results ── */}
      {step === 2 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <div className="card">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-2)" }}>
              <h2 className="text-heading">Running eval</h2>
              <span className="text-caption">{queue.length} call{queue.length !== 1 ? "s" : ""}</span>
            </div>

            {phase === "calling" && (
              <div className="status info">
                <span className="spinner" />Placing call {batchProgress.current} of {batchProgress.total}…
              </div>
            )}
            {phase === "waiting" && (
              <div className="status info">
                <span className="spinner" />Call {batchProgress.current}/{batchProgress.total} in progress
                <span className="text-caption" style={{ marginLeft: "var(--space-2)", color: "var(--accent)" }}>
                  ({calls.filter((c) => c.report).length} finished)
                </span>
              </div>
            )}
            {phase === "error" && <div className="status err">⚠ {error}</div>}
            {phase === "ready" && (
              <div className="status ok">
                All {queue.length} call{queue.length !== 1 ? "s" : ""} complete
              </div>
            )}

            {(phase === "ready" || phase === "error") && (
              <Button variant="secondary" size="sm" onClick={startOver} style={{ marginTop: "var(--space-4)" }}>
                <ArrowLeft size={13} /> New eval
              </Button>
            )}
          </div>

          {calls.length > 1 ? (
            <BatchReport calls={calls} settled={phase === "ready"} />
          ) : calls.length === 1 && calls[0].report ? (
            <Report data={calls[0].report} />
          ) : calls.length === 1 ? (
            <div className="placeholder" style={{ minHeight: 160 }}>
              <span className="spinner" />Waiting for report…
            </div>
          ) : null}
        </div>
      )}

      <AnimatePresence>
        {objectiveModalEntry ? (
          <ObjectiveEditorModal
            key={objectiveModalEntry.id}
            value={objectiveModalEntry.objective}
            onChange={(objective) => patchEntry(objectiveModalEntry.id, { objective })}
            onClose={() => setObjectiveModalEntryId(null)}
          />
        ) : null}
      </AnimatePresence>
    </div>
  );
}
