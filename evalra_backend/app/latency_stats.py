"""Fleet-level E2E latency aggregation from pooled turn samples."""

from typing import Any


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def baseline_call_filter() -> dict[str, Any]:
    """MongoDB filter for normal factual benchmark calls (no stress simulations)."""
    legacy_baseline = {
        "meta.is_baseline_call": {"$exists": False},
        "meta.test_interruptions": {"$ne": True},
        "meta.simulations.barge_in.enabled": {"$ne": True},
        "meta.simulations.ambient_noise.enabled": {"$ne": True},
        "meta.simulations.language_switch.enabled": {"$ne": True},
        "$or": [
            {"meta.background_noise": {"$in": [None, "", "off"]}},
            {"meta.background_noise": {"$exists": False}},
        ],
    }
    return {
        "connection.ended_gracefully": True,
        "$or": [
            {"meta.is_baseline_call": True},
            legacy_baseline,
        ],
    }


def pool_baseline_latencies(docs: list[dict]) -> tuple[list[float], int]:
    """Collect turn latencies from baseline report docs. Returns (samples, call_count)."""
    all_latencies: list[float] = []
    call_count = 0
    for doc in docs:
        latencies = (doc.get("summary") or {}).get("agent_response_latencies") or []
        if not latencies:
            continue
        call_count += 1
        all_latencies.extend(float(x) for x in latencies)
    return all_latencies, call_count


def compute_latency_stats(latencies: list[float]) -> dict[str, float | None]:
    return {
        "avg_s": _avg(latencies),
        "p50_s": _pct(latencies, 50),
        "p99_s": _pct(latencies, 99),
    }
