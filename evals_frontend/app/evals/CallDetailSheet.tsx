"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useWavesurfer } from "@wavesurfer/react";
import { motion } from "framer-motion";
import { Play, Pause, Download, X, Bot, User, Loader2, MessageSquare, ChevronDown, ChevronUp } from "lucide-react";
import type { ReportData } from "../../lib/types";
import { enrichTranscriptOffsets, callDuration } from "../../lib/transcriptTimeline";

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

const API = process.env.NEXT_PUBLIC_EVALS_API || "http://localhost:7870";

// Minimal typings for the browser built-in Translator API (Chromium 138+), which is
// not yet in the standard DOM lib. https://developer.mozilla.org/en-US/docs/Web/API/Translator
type TranslatorAvailability = "unavailable" | "downloadable" | "downloading" | "available";
interface TranslatorOptions {
  sourceLanguage: string;
  targetLanguage: string;
}
interface TranslatorInstance {
  translate(input: string): Promise<string>;
  destroy?(): void;
}
interface TranslatorStatic {
  availability(opts: TranslatorOptions): Promise<TranslatorAvailability>;
  create(opts: TranslatorOptions): Promise<TranslatorInstance>;
}
function getTranslator(): TranslatorStatic | undefined {
  return (globalThis as unknown as { Translator?: TranslatorStatic }).Translator;
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || isNaN(seconds)) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export default function CallDetailSheet({
  data,
  onClose,
}: {
  data: ReportData;
  onClose: () => void;
}) {
  const recordingUrl = data.recording_url ? `${API}${data.recording_url}` : null;
  const hasRecording = Boolean(recordingUrl);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const waveformRef = useRef<HTMLDivElement>(null);

  // Translation state (English toggle).
  const [showEnglish, setShowEnglish] = useState(false);
  const [enText, setEnText] = useState<string[] | null>(null);
  const [translating, setTranslating] = useState(false);
  const [simEventsOpen, setSimEventsOpen] = useState(false);
  const srcLang = (data.meta.language || "").toLowerCase().split("-")[0];
  const translatable = srcLang !== "" && srcLang !== "en";
  const ledger = (data.ledger || []).filter((e) => e.correct !== null);

  const { wavesurfer, isReady } = useWavesurfer({
    container: waveformRef,
    height: 50,
    waveColor: "rgba(255, 255, 255, 0.25)",
    progressColor: "rgba(255, 255, 255, 0.95)",
    cursorColor: "rgba(255, 255, 255, 0.6)",
    barWidth: 2,
    barRadius: 1,
    barGap: 1,
    normalize: true,
    dragToSeek: true,
    hideScrollbar: true,
    cursorWidth: 1,
    url: recordingUrl || undefined,
  });

  // WaveSurfer events
  useEffect(() => {
    if (!wavesurfer) return;
    const subs = [
      wavesurfer.on("play", () => setIsPlaying(true)),
      wavesurfer.on("pause", () => setIsPlaying(false)),
      wavesurfer.on("timeupdate", (t) => setCurrentTime(t)),
      wavesurfer.on("ready", () => setDuration(wavesurfer.getDuration())),
      wavesurfer.on("finish", () => {
        setIsPlaying(false);
        setCurrentTime(0);
      }),
    ];
    return () => subs.forEach((u) => u());
  }, [wavesurfer]);

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function togglePlay() {
    wavesurfer?.playPause();
  }

  // Click a transcript bubble -> seek the recording to that line and play.
  function seekToLine(offset: number | null | undefined) {
    if (!wavesurfer || !duration || offset == null) return;
    wavesurfer.seekTo(Math.min(0.999, offset / duration));
    wavesurfer.play();
  }

  const callDurationSecs = callDuration(data);
  const timedTranscript = useMemo(
    () => (callDurationSecs > 0 ? enrichTranscriptOffsets(data.transcript, callDurationSecs) : []),
    [data.transcript, callDurationSecs]
  );

  // Which line is currently playing (last line whose offset has passed).
  const activeIdx = useMemo(() => {
    if (!hasRecording || !timedTranscript.length) return -1;
    let idx = -1;
    timedTranscript.forEach((t, i) => {
      if (t.offset_s <= currentTime + 0.25) idx = i;
    });
    return idx;
  }, [currentTime, hasRecording, timedTranscript]);

  async function toggleEnglish() {
    if (enText) {
      setShowEnglish((x) => !x);
      return;
    }
    setTranslating(true);
    try {
      // Try the browser's built-in Translator API first (Chromium 138+).
      const T = getTranslator();
      if (T) {
        const avail = await T.availability({ sourceLanguage: srcLang, targetLanguage: "en" }).catch(() => "unavailable");
        if (avail !== "unavailable") {
          const translator = await T.create({ sourceLanguage: srcLang, targetLanguage: "en" });
          const out = await Promise.all(
            data.transcript.map((t) =>
              t.content ? translator.translate(t.content) : Promise.resolve("")
            )
          );
          translator.destroy?.();
          setEnText(out);
          setShowEnglish(true);
          return;
        }
      }
      // Fallback: Google Translate (client=gtx, no API key required).
      const lines = data.transcript.map((t) => t.content || "");
      const translations = await Promise.all(
        lines.map(async (line) => {
          if (!line) return "";
          const url =
            `https://translate.googleapis.com/translate_a/single?client=gtx` +
            `&sl=${encodeURIComponent(srcLang)}&tl=en&dt=t` +
            `&q=${encodeURIComponent(line)}`;
          const res = await fetch(url);
          const json = await res.json();
          // json[0] is an array of [translated_chunk, original_chunk, ...] segments.
          return (json[0] as [string, string][]).map((seg) => seg[0]).join("") || line;
        })
      );
      setEnText(translations);
      setShowEnglish(true);
    } catch {
      /* leave original text */
    } finally {
      setTranslating(false);
    }
  }

  return (
    <motion.div
      className="cds-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className="cds-sheet"
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "tween", duration: 0.28, ease: "easeOut" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="cds-head">
          <div>
            <div className="cds-title">Call recording & transcript</div>
            <div className="cds-sub">{data.call_id}</div>
          </div>
          <button className="cds-iconbtn" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        {/* Recording hero */}
        {hasRecording ? (
          <motion.div
            className="cds-player"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <button
              className="cds-play"
              onClick={togglePlay}
              disabled={!isReady}
              aria-label={isPlaying ? "Pause" : "Play"}
            >
              {!isReady ? (
                <Loader2 size={16} className="cds-spin" />
              ) : isPlaying ? (
                <Pause size={16} />
              ) : (
                <Play size={16} />
              )}
            </button>
            <div className="cds-wave-wrap">
              <div ref={waveformRef} className="cds-wave" />
            </div>
            <div className="cds-time">
              <span className="cds-time-now">{formatTime(currentTime)}</span>
              <span className="cds-time-sep">/</span>
              <span className="cds-time-dur">{formatTime(duration)}</span>
            </div>
            <a
              className="cds-iconbtn cds-dl"
              href={recordingUrl || "#"}
              download={`${data.call_id}.wav`}
              aria-label="Download recording"
            >
              <Download size={14} />
            </a>
          </motion.div>
        ) : (
          <div className="cds-norec">Recording not available for this call.</div>
        )}

        {ledger.length > 0 && (
          <>
            <button
              type="button"
              className="cds-tbar cds-tbar--toggle"
              onClick={() => setSimEventsOpen((open) => !open)}
              aria-expanded={simEventsOpen}
              aria-controls="cds-sim-events"
            >
              <span className="cds-tbar-title">Simulation events ({ledger.length})</span>
              {simEventsOpen ? (
                <ChevronUp size={14} strokeWidth={2} aria-hidden />
              ) : (
                <ChevronDown size={14} strokeWidth={2} aria-hidden />
              )}
            </button>
            {simEventsOpen && (
              <ul id="cds-sim-events" className="cds-sim-events">
                {ledger.map((e, i) => (
                  <li key={i}>
                    {e.correct ? "✓" : "✗"} {KIND_LABELS[e.kind] || e.kind} @ {e.offset_s.toFixed(1)}s
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {/* Transcript */}
        <div className="cds-tbar">
          <span className="cds-tbar-title">
            Transcript ({data.transcript.length})
          </span>
          <div className="cds-tbar-actions">
            {translatable && (
              <button className="cds-textbtn" onClick={toggleEnglish} disabled={translating}>
                {translating ? "Translating…" : showEnglish ? "Show original" : "Show in English"}
              </button>
            )}
            {hasRecording && <span className="cds-hint">Click a line to play it</span>}
          </div>
        </div>

        <div className="cds-transcript">
          {data.transcript.length === 0 ? (
            <div className="cds-empty">
              <MessageSquare size={22} />
              <span>No transcript available</span>
            </div>
          ) : (
            timedTranscript.map((t, i) => {
              const tester = t.role === "assistant";
              const seekable = hasRecording && typeof t.offset_s === "number";
              const content = showEnglish && enText ? enText[i] : t.content;
              return (
                <div key={i} className={`cds-row ${tester ? "tester" : "voicera"}`}>
                  <div className={`cds-avatar ${tester ? "tester" : "voicera"}`}>
                    {tester ? <User size={15} /> : <Bot size={15} />}
                  </div>
                  <div className="cds-msg">
                    <div className="cds-who">
                      {tester ? "Evals agent" : "Agent"}
                      {typeof t.offset_s === "number" ? (
                        <span className="cds-offset">{formatTime(t.offset_s)}</span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      className={`cds-bubble ${tester ? "tester" : "voicera"} ${
                        seekable ? "seekable" : ""
                      } ${activeIdx === i ? "active" : ""}`}
                      onClick={() => seekable && seekToLine(t.offset_s)}
                      disabled={!seekable}
                    >
                      {content}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}