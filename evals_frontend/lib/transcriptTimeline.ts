import type { ReportData } from "./types";

export interface TimelineSegment {
  role: "user" | "assistant";
  start: number;
  end: number;
  content: string;
}

const MIN_SEGMENT_S = 0.35;

/** Seconds from call start for each transcript line (interpolates missing assistant offsets). */
export function enrichTranscriptOffsets(
  transcript: ReportData["transcript"],
  duration: number
): Array<ReportData["transcript"][number] & { offset_s: number }> {
  if (!transcript.length || duration <= 0) return [];

  const lines = transcript.map((m) => ({ ...m }));
  const known = lines
    .map((m, i) => ({ i, off: m.offset_s }))
    .filter((x): x is { i: number; off: number } => typeof x.off === "number" && x.off >= 0);

  if (known.length === 0) {
    const step = duration / Math.max(lines.length, 1);
    return lines.map((m, i) => ({
      ...m,
      offset_s: Math.min(duration, round2(i * step)),
    }));
  }

  const first = known[0];
  for (let i = 0; i < first.i; i++) {
    lines[i].offset_s = round2((first.off * (i + 1)) / (first.i + 1));
  }

  for (let k = 0; k < known.length - 1; k++) {
    const left = known[k];
    const right = known[k + 1];
    const span = right.i - left.i;
    if (span <= 1) continue;
    for (let j = 1; j < span; j++) {
      const idx = left.i + j;
      lines[idx].offset_s = round2(
        left.off + ((right.off - left.off) * j) / span
      );
    }
  }

  const last = known[known.length - 1];
  const tail = lines.length - last.i - 1;
  for (let j = 1; j <= tail; j++) {
    const idx = last.i + j;
    lines[idx].offset_s = round2(
      last.off + ((duration - last.off) * j) / (tail + 1)
    );
  }

  for (const m of lines) {
    if (typeof m.offset_s !== "number") {
      m.offset_s = last.off;
    }
    m.offset_s = Math.min(duration, Math.max(0, m.offset_s));
  }

  return lines as Array<ReportData["transcript"][number] & { offset_s: number }>;
}

export function buildLaneSegments(
  transcript: ReportData["transcript"],
  role: "user" | "assistant",
  duration: number
): TimelineSegment[] {
  const enriched = enrichTranscriptOffsets(transcript, duration).filter((m) => m.role === role);
  if (!enriched.length) return [];

  return enriched.map((m, i) => {
    const start = m.offset_s;
    const next = enriched[i + 1]?.offset_s ?? duration;
    const end = Math.min(duration, Math.max(next, start + MIN_SEGMENT_S));
    return { role, start, end, content: m.content };
  });
}

export function callDuration(data: ReportData): number {
  const fromSummary = data.summary.call_duration_secs;
  if (typeof fromSummary === "number" && fromSummary > 0) return fromSummary;

  const offsets = [
    ...data.transcript.map((m) => m.offset_s).filter((v): v is number => typeof v === "number"),
    ...(data.ledger || []).map((e) => e.offset_s),
  ];
  return offsets.length ? Math.max(...offsets) : 0;
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}

export function fmtClock(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtTooltip(content: string): string {
  return content.length > 160 ? `${content.slice(0, 160)}…` : content;
}
