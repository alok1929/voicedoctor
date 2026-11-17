from typing import Any
from pydantic import BaseModel, Field


class PulseIn(BaseModel):
    """A recurring eval test the user configures — fired on an interval by the cron runner."""
    name: str
    voicera_number: str
    objective: str | None = None
    expected_outcome: str | None = None
    persona: str | None = None
    language: str | None = None
    evals: object = "standard"
    simulations: dict | None = None
    interval_minutes: int = 60
    max_runs: int | None = None  # None = run forever; otherwise auto-disable after this many fires


class PulseUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    interval_minutes: int | None = None
    voicera_number: str | None = None
    objective: str | None = None
    expected_outcome: str | None = None
    persona: str | None = None
    language: str | None = None
    evals: object = None
    simulations: dict | None = None
    max_runs: int | None = None
    clear_max_runs: bool = False  # set true to explicitly clear a previously-set limit


class PulseOut(BaseModel):
    id: str
    name: str
    voicera_number: str
    objective: str | None = None
    expected_outcome: str | None = None
    persona: str | None = None
    language: str | None = None
    evals: object = "standard"
    simulations: dict | None = None
    interval_minutes: int
    max_runs: int | None = None
    run_count: int = 0
    enabled: bool
    owner_email: str
    org_id: str
    created_at: str
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_result: dict | None = None


class ReportIn(BaseModel):
    """Accepts any report shape the caller server emits — stored verbatim."""
    call_id: str
    generated_at: str
    outcome: str = "unknown"
    voicera_number: str = ""

    model_config = {"extra": "allow"}


class ReportListItem(BaseModel):
    call_id: str
    generated_at: str
    outcome: str
    eval_result: str | None = None
    voicera_number: str
    objective: str = ""
    csat: Any = None
    language: str = "en"
    simulations: list[str] = []
    simulation_sound: str | None = None


class MetricsSummary(BaseModel):
    n: int
    # Reliability
    connection_success_rate: float | None
    graceful_termination_rate: float | None
    mid_call_drop_rate: float | None
    # Quality
    avg_csat: float | None
    avg_duration_secs: float | None
    avg_voicera_wpm: float | None
    outcome_distribution: dict[str, int]
    # Baseline factual E2E latency (pooled turn samples across stress-test-free calls)
    baseline_n: int = 0
    latency_scope: str = "baseline"  # "baseline" | "all" (fallback when no baseline calls)
    baseline_agent_latency_avg_s: float | None = None
    baseline_agent_latency_p50_s: float | None = None
    baseline_agent_latency_p99_s: float | None = None
    # Interruption handling
    avg_interruption_detection_accuracy: float | None = None
    avg_barge_in_agent_talk_to_interruption_avg_s: float | None = None
    avg_interruption_response_latency_avg_s: float | None = None
    avg_false_interruption_rate: float | None = None
    # Dead air
    avg_dead_air_rate_per_min: float | None = None
