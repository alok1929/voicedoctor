export interface LedgerEntry {
  kind: string;
  expected: string;
  offset_s: number;
  reacted: boolean | null;
  latency_s: number | null;
  correct: boolean | null;
}

/** Measured call summary from MetricsCollector.summary(). */
export interface ReportSummary {
  agent_response_latencies?: number[];
  agent_latency_avg_s?: number | null;
  agent_latency_p50_s?: number | null;
  agent_latency_p90_s?: number | null;
  agent_latency_p95_s?: number | null;
  agent_latency_p99_s?: number | null;
  agent_turns?: number | null;
  [key: string]: number | boolean | null | number[] | undefined;
}

export interface ReportData {
  call_id: string;
  generated_at: string;
  meta: {
    voicera_number: string;
    language?: string;
    objective: string;
    expected_outcome: string;
    background_noise?: string;
    noise_volume?: number | null;
    test_interruptions?: boolean;
    barge_in_style?: string | null;
    simulations?: Record<string, unknown>;
    evals: string[];
  };
  summary: ReportSummary;
  judge: {
    metrics: Record<string, { value: unknown; reason?: string }>;
    recommendations: string[];
    overall: string;
  };
  metric_catalog: Record<string, { label: string; category: string }>;
  recording_url?: string | null;
  outcome?: string;
  connection?: {
    outcome: string;
    connected: boolean;
    ended_gracefully: boolean;
    dropped_midcall: boolean;
  };
  ledger?: LedgerEntry[];
  transcript: { role: string; content: string; ts?: string | null; offset_s?: number | null }[];
}
