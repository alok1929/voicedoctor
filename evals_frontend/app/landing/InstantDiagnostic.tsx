"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2, CheckCircle2, PhoneCall, ArrowRight, AlertCircle, Volume2, MessageSquare, VolumeX, Play,
} from "lucide-react";
import type { ReportData } from "../../lib/types";
import styles from "./landing.module.css";

const API = process.env.NEXT_PUBLIC_EVALS_API || "http://localhost:7870";

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
];

// What we actually enable on the call — shown to the user verbatim, nothing fabricated.
const TESTS_RUN = [
  { Icon: Volume2, label: "Background noise (café)" },
  { Icon: MessageSquare, label: "Interruption recovery" },
  { Icon: VolumeX, label: "Silence handling" },
];

const VITALS: { key: keyof ReportData["summary"] | string; label: string; fmt: "secs" | "num" }[] = [
  { key: "agent_latency_avg_s", label: "Avg Response Latency", fmt: "secs" },
  { key: "agent_latency_p95_s", label: "P95 Latency", fmt: "secs" },
  { key: "interruption_response_latency_avg_s", label: "Interruption Recovery", fmt: "secs" },
  { key: "call_duration_secs", label: "Call Duration", fmt: "secs" },
];

function fmtSecs(v: unknown): string | null {
  if (v == null || typeof v !== "number") return null;
  return v < 1 ? `${Math.round(v * 1000)}ms` : `${v.toFixed(2)}s`;
}
function fmtNum(v: unknown): string | null {
  if (v == null || typeof v !== "number") return null;
  return String(v);
}

function buildRequestBody(voiceraNumber: string, language: string) {
  return {
    voicera_number: voiceraNumber,
    evals: "standard",
    language,
    max_duration_minutes: 3,
    simulations: {
      ambient_noise: { enabled: true, type: "cafe", volume: 0.30 },
      barge_in: { enabled: true, real_count: 1, after_secs: 2, style: "speech", sound_type: "trucksounds", sound_volume: 0.8, fake_count: 0, fake_burst_secs: 2, fake_volume: 0.8 },
      language_switch: { enabled: false, switch_to: "hi", after_turn: 1 },
    },
  };
}

export default function InstantDiagnostic() {
  const [phase, setPhase] = useState<"idle" | "calling" | "running" | "done" | "error">("idle");
  const [language, setLanguage] = useState("en");
  const [number, setNumber] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [report, setReport] = useState<ReportData | null>(null);
  const [error, setError] = useState("");

  const abortRef = useRef(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    abortRef.current = true;
    if (pollRef.current) clearInterval(pollRef.current);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
  }, []);

  function waitForReport(id: string, deadlineMs: number): Promise<ReportData> {
    return new Promise((resolve, reject) => {
      const iv = setInterval(async () => {
        if (abortRef.current) { clearInterval(iv); reject(new Error("aborted")); return; }
        if (Date.now() > deadlineMs) { clearInterval(iv); reject(new Error("Diagnostic timed out waiting for the report")); return; }
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

  async function runDiagnostic() {
    if (phase === "calling" || phase === "running") return;
    abortRef.current = false;
    setError("");
    setReport(null);
    setElapsed(0);
    setPhase("calling");

    elapsedRef.current = setInterval(() => setElapsed((n) => n + 1), 1000);

    try {
      const res = await fetch(`${API}/api/evals-call`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildRequestBody(number, language)),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);

      setPhase("running");
      const deadline = Date.now() + (3 * 60 + 180) * 1000;
      const rep = await waitForReport(data.call_id, deadline);
      if (abortRef.current) return;
      setReport(rep);
      setPhase("done");
    } catch (err) {
      if (abortRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    } finally {
      if (elapsedRef.current) clearInterval(elapsedRef.current);
    }
  }

  const verdict = report?.judge?.overall || "";
  const outcome = report?.outcome;
  const connected = report?.connection?.connected;
  const recordingUrl = report?.recording_url
    ? (report.recording_url.startsWith("http") ? report.recording_url : `${API}${report.recording_url}`)
    : null;

  return (
    <div className={styles.diagSection}>
      <div className={styles.diagHeadWrap}>
        <h2 className={styles.diagHeadline}>Diagnose your voice AI in under a minute</h2>
        <p className={styles.diagSub}>Enter the number your agent answers on. We place a real call and run it through the full stress suite — no signup.</p>
      </div>

      <div className={styles.diagCard}>
        {phase === "idle" && (
          <div className={styles.diagForm}>
            <div className={styles.diagInputRow}>
              <select className={styles.diagCc} value={language} onChange={(e) => setLanguage(e.target.value)}>
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
              <input
                className={styles.diagInput}
                type="tel"
                placeholder="+91 98765 43210"
                value={number}
                onChange={(e) => setNumber(e.target.value.replace(/[^\d+]/g, ""))}
              />
              <button
                type="button"
                className={styles.diagBtn}
                disabled={number.length < 8}
                onClick={runDiagnostic}
              >
                Run Diagnostic <ArrowRight size={15} />
              </button>
            </div>
            <div className={styles.diagHint}>Free diagnostic call · real phone call to the number above</div>
          </div>
        )}

        {(phase === "calling" || phase === "running") && (
          <div className={styles.diagRunWrap}>
            <div className={styles.diagRunHead}>
              <PhoneCall size={16} />
              <span>{phase === "calling" ? `Calling ${number}…` : `Call in progress — ${elapsed}s elapsed`}</span>
            </div>
            <div className={styles.diagSteps}>
              {TESTS_RUN.map(({ Icon, label }, i) => (
                <motion.div
                  key={label}
                  className={styles.diagStep}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, delay: i * 0.1 }}
                >
                  {phase === "running" ? <Loader2 size={14} className={styles.spin} /> : <Icon size={14} />}
                  <span>{label}</span>
                </motion.div>
              ))}
            </div>
          </div>
        )}

        {phase === "error" && (
          <div className={styles.diagError}>
            <AlertCircle size={15} />
            <span>{error}</span>
            <button type="button" className={styles.diagRetry} onClick={() => setPhase("idle")}>Try again</button>
          </div>
        )}

        <AnimatePresence>
          {phase === "done" && report && (
            <motion.div
              className={styles.reportWrap}
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              transition={{ duration: 0.5 }}
            >
              <div className={styles.reportTop}>
                <div className={styles.reportOutcome}>
                  {connected ? <CheckCircle2 size={20} color="#3E7E72" /> : <AlertCircle size={20} color="#C06A52" />}
                </div>
                <div className={styles.reportTopText}>
                  <div className={styles.reportTopLabel}>Diagnosis{outcome ? ` · ${outcome}` : ""}</div>
                  <div className={styles.reportTopDesc}>{verdict || "Call completed — see metrics below."}</div>
                </div>
              </div>

              <div className={styles.vitalsGrid}>
                {VITALS.map((v) => {
                  const raw = report.summary?.[v.key as string];
                  const display = v.fmt === "secs" ? fmtSecs(raw) : fmtNum(raw);
                  if (display == null) return null;
                  return (
                    <div key={v.label} className={styles.vitalCell}>
                      <CheckCircle2 size={13} color="#3E7E72" />
                      <div>
                        <div className={styles.vitalVal}>{display}</div>
                        <div className={styles.vitalLabel}>{v.label}</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {report.judge?.recommendations?.length > 0 && (
                <div className={styles.reportCol}>
                  <div className={styles.reportColTitle}>Recommended treatment</div>
                  <ul className={styles.treatList}>
                    {report.judge.recommendations.map((t) => <li key={t}>{t}</li>)}
                  </ul>
                </div>
              )}

              {report.transcript?.length > 0 && (
                <div className={styles.reportCol}>
                  <div className={styles.reportColTitle}>Transcript</div>
                  <div className={styles.transcriptPreview}>
                    {report.transcript.slice(0, 4).map((t, i) => (
                      <div key={i} className={styles.transcriptLine}>
                        <span className={styles.transcriptRole}>{t.role}</span>
                        <span>{t.content}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {recordingUrl && (
                <div className={styles.reportCol}>
                  <div className={styles.reportColTitle}><Play size={12} /> Listen to the call</div>
                  <audio controls src={recordingUrl} className={styles.audioPlayer} />
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
