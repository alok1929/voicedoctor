"""Post-call report: compute words-per-minute, run the LLM judge, persist a
structured JSON document locally, and push to evalra_backend for cross-call analytics."""

import json
import os
from datetime import datetime, timezone

import requests
from loguru import logger

from app import config
from app.judge import run_judge

# evalra_backend URL (optional — if unset or unreachable, local file is the only record).
EVALRA_BACKEND_URL = os.getenv("EVALRA_BACKEND_URL", "").rstrip("/")

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "recordings")


def _resolve_eval_context(run_config: dict) -> dict:
    """Map run_config fields to evaluation context, preserving legacy key names.

    Reads `test_scenario` / `expected_understanding` when present, otherwise falls
    back to `objective` / `expected_outcome`. Dashboards and analytics continue to
    consume `objective` and `expected_outcome` in report meta.
    """
    evaluation_mode = run_config.get("evaluation_mode") or config.DEFAULT_EVALUATION_MODE
    test_scenario = (
        run_config.get("test_scenario")
        or run_config.get("objective")
        or config.TEST_OBJECTIVE
    )
    expected_understanding = (
        run_config.get("expected_understanding")
        or run_config.get("expected_outcome")
        or test_scenario
    )
    return {
        "evaluation_mode": evaluation_mode,
        "test_scenario": test_scenario,
        "expected_understanding": expected_understanding,
        "objective": test_scenario,
        "expected_outcome": expected_understanding,
    }


def _wpm(words, secs):
    return round(words / (secs / 60.0), 1) if secs and secs > 0 else None


def _ambient_noise_meta(run_config: dict) -> tuple[str, float | None]:
    """Resolve noise preset + volume from simulations or legacy flat fields."""
    sims = config.normalize_simulations(run_config.get("simulations"))
    if sims["ambient_noise"]["enabled"]:
        return sims["ambient_noise"]["type"], sims["ambient_noise"]["volume"]
    return run_config.get("background_noise", "off"), run_config.get("noise_volume")


def _offset_secs(ts, recording_start, mono_s=None):
    """Seconds into the recording for a transcript line.

    Prefer monotonic offset captured at transcript time (works for assistant turns).
    Fall back to ISO timestamp vs recording start epoch.
    """
    if mono_s is not None:
        try:
            return round(max(0.0, float(mono_s)), 2)
        except (TypeError, ValueError):
            pass
    if not ts or recording_start is None:
        return None
    try:
        return round(max(0.0, datetime.fromisoformat(ts).timestamp() - recording_start), 2)
    except (ValueError, TypeError):
        return None


def _interpolate_transcript_offsets(transcript, duration):
    """Fill missing offset_s by linear interpolation between known anchors."""
    if not transcript or not duration:
        return transcript
    lines = [dict(m) for m in transcript]
    known = [(i, m["offset_s"]) for i, m in enumerate(lines) if m.get("offset_s") is not None]
    if not known:
        step = duration / max(len(lines), 1)
        for i, m in enumerate(lines):
            m["offset_s"] = round(min(duration, i * step), 2)
        return lines

    first_i, first_off = known[0]
    for i in range(first_i):
        lines[i]["offset_s"] = round(first_off * (i + 1) / (first_i + 1), 2)

    for (left_i, left_off), (right_i, right_off) in zip(known, known[1:]):
        span = right_i - left_i
        if span <= 1:
            continue
        for j in range(1, span):
            idx = left_i + j
            lines[idx]["offset_s"] = round(left_off + (right_off - left_off) * j / span, 2)

    last_i, last_off = known[-1]
    tail = len(lines) - last_i - 1
    for j in range(1, tail + 1):
        idx = last_i + j
        lines[idx]["offset_s"] = round(last_off + (duration - last_off) * j / (tail + 1), 2)

    for m in lines:
        if m.get("offset_s") is None:
            m["offset_s"] = last_off
        m["offset_s"] = round(min(duration, max(0.0, float(m["offset_s"]))), 2)
    return lines


# Map the call outcome to the three fleet-level per-call primitives. Aggregating these
# across many calls gives Connection Success / Graceful Termination / Mid-Call Drop rates.
def _connection_primitives(outcome):
    o = (outcome or "unknown").lower()
    return {
        "outcome": o,
        "connected": o not in ("never_connected", "unknown"),
        "ended_gracefully": o == "completed",
        "dropped_midcall": o == "disconnected",
    }


def build_report(
    call_id, run_config, summary, transcript, recording_start=None, outcome=None, ledger=None
):
    """Compute WPM, run the judge, and write the JSON report. Returns the path."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    eval_ctx = _resolve_eval_context(run_config)
    metric_keys = run_config.get("evals") or []

    # words/min from transcript + measured speaking time
    user_words = sum(len(m["content"].split()) for m in transcript if m["role"] == "user")
    bot_words = sum(len(m["content"].split()) for m in transcript if m["role"] == "assistant")
    summary = dict(summary)
    summary["voicera_wpm"] = _wpm(user_words, summary.get("voicera_speaking_secs"))
    summary["tester_wpm"] = _wpm(bot_words, summary.get("tester_speaking_secs"))

    transcript_lines = [f'{m["role"]}: {m["content"]}' for m in transcript]
    judge = run_judge(
        eval_ctx["test_scenario"],
        eval_ctx["expected_understanding"],
        metric_keys,
        summary,
        transcript_lines,
        evaluation_mode=eval_ctx["evaluation_mode"],
        barge_in_style=run_config.get("barge_in_style")
        or (config.normalize_simulations(run_config.get("simulations"))["barge_in"]["style"]),
    )

    # Tag each line with its offset (seconds) into the recording so the UI can seek the
    # audio when a transcript bubble is clicked. Interpolate gaps so assistant turns
    # (often missing ISO timestamps) still appear on the conversation timeline.
    transcript = [
        {
            **m,
            "offset_s": _offset_secs(m.get("ts"), recording_start, m.get("mono_s")),
        }
        for m in transcript
    ]
    duration = summary.get("call_duration_secs")
    if duration and duration > 0:
        transcript = _interpolate_transcript_offsets(transcript, float(duration))

    noise_type, noise_volume = _ambient_noise_meta(run_config)

    # Expose the recording only if it was actually captured for this call.
    recording_exists = os.path.exists(os.path.join(RECORDINGS_DIR, f"{call_id}.wav"))
    recording_url = f"/api/report/{call_id}/recording" if recording_exists else None

    # Catalog so the UI can label/group judge metrics without duplicating definitions.
    catalog = {
        key: {"label": config.LLM_JUDGE_METRICS[key][1], "category": config.LLM_JUDGE_METRICS[key][0]}
        for key in metric_keys
        if key in config.LLM_JUDGE_METRICS
    }

    data = {
        "call_id": call_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recording_url": recording_url,
        "outcome": (outcome or "unknown"),
        "connection": _connection_primitives(outcome),
        "meta": {
            "voicera_number": run_config.get("voicera_number", ""),
            "language": run_config.get("language") or "en",
            "evaluation_mode": eval_ctx["evaluation_mode"],
            "objective": eval_ctx["objective"],
            "expected_outcome": eval_ctx["expected_outcome"],
            "background_noise": noise_type,
            "noise_volume": noise_volume,
            "test_interruptions": bool(run_config.get("test_interruptions")),
            "barge_in_style": run_config.get("barge_in_style")
            or config.normalize_simulations(run_config.get("simulations"))["barge_in"]["style"],
            "simulations": run_config.get("simulations") or {},
            "is_baseline_call": config.is_baseline_call(run_config),
            "evals": metric_keys,
            "pulse_id": run_config.get("pulse_id"),
            "org_id": run_config.get("org_id"),
        },
        "summary": summary,
        "judge": judge,
        "metric_catalog": catalog,
        "ledger": ledger or [],
        "transcript": transcript,
    }

    path = os.path.join(REPORTS_DIR, f"report_{call_id}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"📄 Report written: {path}")

    # Push to evalra_backend (non-blocking best-effort; local file is always the source of truth).
    if EVALRA_BACKEND_URL:
        try:
            # Flatten top-level voicera_number for evalra_backend's index queries.
            payload = dict(data)
            payload["voicera_number"] = (data.get("meta") or {}).get("voicera_number", "")
            resp = requests.post(
                f"{EVALRA_BACKEND_URL}/reports",
                json=payload,
                timeout=10,
            )
            if resp.ok:
                logger.info(f"☁️  Report pushed to evalra_backend: {call_id}")
            else:
                logger.warning(f"evalra_backend rejected report {call_id}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"evalra_backend push failed for {call_id}: {e}")

    return path


def write_failure_report(call_id: str, run_config: dict, reason: str = "never_connected") -> str:
    """Write a minimal failure report when the call never connected (no pipeline ran)."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    eval_ctx = _resolve_eval_context(run_config)
    metric_keys = run_config.get("evals") or []
    noise_type, noise_volume = _ambient_noise_meta(run_config)
    data = {
        "call_id": call_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recording_url": None,
        "outcome": reason,
        "connection": _connection_primitives(reason),
        "meta": {
            "voicera_number": run_config.get("voicera_number", ""),
            "language": run_config.get("language") or "en",
            "evaluation_mode": eval_ctx["evaluation_mode"],
            "objective": eval_ctx["objective"],
            "expected_outcome": eval_ctx["expected_outcome"],
            "background_noise": noise_type,
            "noise_volume": noise_volume,
            "test_interruptions": bool(run_config.get("test_interruptions")),
            "barge_in_style": run_config.get("barge_in_style")
            or config.normalize_simulations(run_config.get("simulations"))["barge_in"]["style"],
            "simulations": run_config.get("simulations") or {},
            "is_baseline_call": config.is_baseline_call(run_config),
            "evals": metric_keys,
            "pulse_id": run_config.get("pulse_id"),
            "org_id": run_config.get("org_id"),
        },
        "summary": {},
        "judge": {"overall": None, "metrics": {}, "reasoning": f"Call did not connect: {reason}"},
        "metric_catalog": {},
        "ledger": [],
        "transcript": [],
    }
    path = os.path.join(REPORTS_DIR, f"report_{call_id}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.warning(f"📄 Failure report written ({reason}): {path}")

    if EVALRA_BACKEND_URL:
        try:
            payload = dict(data)
            payload["voicera_number"] = run_config.get("voicera_number", "")
            resp = requests.post(f"{EVALRA_BACKEND_URL}/reports", json=payload, timeout=10)
            if not resp.ok:
                logger.warning(f"evalra_backend rejected failure report {call_id}: {resp.status_code}")
        except Exception as e:
            logger.warning(f"evalra_backend push failed for failure report {call_id}: {e}")

    return path
