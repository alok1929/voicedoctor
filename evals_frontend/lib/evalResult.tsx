export type EvalResult = "pass" | "fail" | "review" | string | null | undefined;

export type EvalResultTone = "ok" | "warn" | "info" | "neutral";

const PILL: Record<string, { cls: string; label: string; tone: EvalResultTone }> = {
  pass: { cls: "badge ok", label: "Pass", tone: "ok" },
  fail: { cls: "badge warn", label: "Not passed", tone: "warn" },
  failed: { cls: "badge warn", label: "Not passed", tone: "warn" },
  review: { cls: "badge info", label: "Needs review", tone: "info" },
  review_required: { cls: "badge info", label: "Needs review", tone: "info" },
};

function normalizeKey(result: EvalResult): string | null {
  if (result == null || result === "") return null;
  const key = String(result).toLowerCase();
  if (key === "pass") return "pass";
  if (key === "fail" || key === "failed") return "fail";
  if (key === "review" || key === "review_required") return "review";
  return key;
}

export function evalResultStyle(result: EvalResult): { cls: string; label: string; tone: EvalResultTone } {
  const key = normalizeKey(result);
  if (!key) return { cls: "badge neutral", label: "—", tone: "neutral" };
  return PILL[key] || {
    cls: "badge neutral",
    label: key.replace(/_/g, " "),
    tone: "neutral",
  };
}

export function evalResultLabel(result: EvalResult): string {
  return evalResultStyle(result).label;
}

export function EvalResultPill({ result }: { result: EvalResult }) {
  const { cls, label } = evalResultStyle(result);
  return <span className={cls}>{label}</span>;
}

/** Prefer API `eval_result`; fall back to nested judge metrics when present. */
export function evalResultFromReport(report: {
  eval_result?: EvalResult;
  judge?: { metrics?: Record<string, { value?: unknown }> };
}): EvalResult {
  if (report.eval_result != null && report.eval_result !== "") {
    return report.eval_result;
  }
  const raw = report.judge?.metrics?.expected_outcome?.value;
  if (raw == null) return null;
  const v = String(raw).toLowerCase();
  if (v === "pass") return "pass";
  if (v === "fail" || v === "failed") return "fail";
  if (v === "review_required") return "review";
  return v;
}
