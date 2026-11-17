from fastapi import APIRouter, Depends
from app.auth import CurrentUser, get_current_user
from app.database import reports_col
from app.eval_result import eval_result_from_doc
from app.latency_stats import baseline_call_filter, compute_latency_stats, pool_baseline_latencies
from app.models import MetricsSummary

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummary)
async def summary(user: CurrentUser = Depends(get_current_user)):
    col = reports_col()
    org_filter = {"org_id": user.org_id}
    total = await col.count_documents(org_filter)
    if total == 0:
        return MetricsSummary(
            n=0,
            connection_success_rate=None,
            graceful_termination_rate=None,
            mid_call_drop_rate=None,
            avg_csat=None,
            avg_duration_secs=None,
            avg_voicera_wpm=None,
            outcome_distribution={},
        )

    def _avg_field(field):
        """Return MongoDB $group accumulators for averaging a nullable numeric field.
        Output keys use __ instead of . because MongoDB rejects dotted output field names."""
        key = field.replace(".", "__")
        return {
            f"{key}_sum": {"$sum": {"$ifNull": [f"${field}", 0]}},
            f"{key}_count": {"$sum": {"$cond": [{"$gt": [f"${field}", None]}, 1, 0]}},
        }

    group_stage: dict = {
        "_id": None,
        "n": {"$sum": 1},
        "connected": {"$sum": {"$cond": [{"$eq": ["$connection.connected", True]}, 1, 0]}},
        "graceful": {"$sum": {"$cond": [{"$eq": ["$connection.ended_gracefully", True]}, 1, 0]}},
        "dropped": {"$sum": {"$cond": [{"$eq": ["$connection.dropped_midcall", True]}, 1, 0]}},
        **_avg_field("_csat"),
        **_avg_field("_duration_secs"),
        **_avg_field("_voicera_wpm"),
        **_avg_field("summary.interruption_detection_accuracy"),
        **_avg_field("summary.barge_in_agent_talk_to_interruption_avg_s"),
        **_avg_field("summary.interruption_response_latency_avg_s"),
        **_avg_field("summary.false_interruption_rate"),
        **_avg_field("summary.dead_air_rate_per_min"),
    }

    agg = await col.aggregate([{"$match": org_filter}, {"$group": group_stage}]).to_list(1)
    r = agg[0] if agg else {}

    n = r.get("n", total)

    def rate(k): return round(r.get(k, 0) / n, 3) if n else None

    def avg(s_key, c_key=None, decimals=1):
        if c_key is None:
            c_key = s_key + "_count"
            s_key = s_key + "_sum"
        c = r.get(c_key, 0)
        return round(r.get(s_key, 0) / c, decimals) if c > 0 else None

    def avg_f(field, decimals=3):
        key = field.replace(".", "__")
        return avg(f"{key}_sum", f"{key}_count", decimals)

    # Pool turn-level latencies across baseline factual calls (not average of call P50/P99).
    baseline_docs = await col.find(
        {**baseline_call_filter(), **org_filter},
        {"summary.agent_response_latencies": 1},
    ).to_list(length=None)
    pooled_latencies, baseline_n = pool_baseline_latencies(baseline_docs)
    latency_scope = "baseline"
    if not pooled_latencies:
        # No stress-test-free baseline calls — fall back to all connected calls with samples.
        latency_scope = "all"
        fallback_docs = await col.find(
            {
                **org_filter,
                "connection.connected": True,
                "summary.agent_response_latencies.0": {"$exists": True},
            },
            {"summary.agent_response_latencies": 1},
        ).to_list(length=None)
        pooled_latencies, baseline_n = pool_baseline_latencies(fallback_docs)
    baseline_stats = compute_latency_stats(pooled_latencies)

    # Outcome distribution
    dist_cursor = col.aggregate([
        {"$match": org_filter},
        {"$group": {"_id": "$outcome", "count": {"$sum": 1}}},
    ])
    dist_docs = await dist_cursor.to_list(20)
    dist = {d["_id"]: d["count"] for d in dist_docs if d.get("_id")}

    return MetricsSummary(
        n=n,
        connection_success_rate=rate("connected"),
        graceful_termination_rate=rate("graceful"),
        mid_call_drop_rate=rate("dropped"),
        avg_csat=avg("_csat_sum", "_csat_count", 0),
        avg_duration_secs=avg("_duration_secs_sum", "_duration_secs_count", 0),
        avg_voicera_wpm=avg("_voicera_wpm_sum", "_voicera_wpm_count", 0),
        outcome_distribution=dist,
        baseline_n=baseline_n,
        latency_scope=latency_scope,
        baseline_agent_latency_avg_s=baseline_stats["avg_s"],
        baseline_agent_latency_p50_s=baseline_stats["p50_s"],
        baseline_agent_latency_p99_s=baseline_stats["p99_s"],
        avg_interruption_detection_accuracy=avg_f("summary.interruption_detection_accuracy"),
        avg_barge_in_agent_talk_to_interruption_avg_s=avg_f("summary.barge_in_agent_talk_to_interruption_avg_s"),
        avg_interruption_response_latency_avg_s=avg_f("summary.interruption_response_latency_avg_s"),
        avg_false_interruption_rate=avg_f("summary.false_interruption_rate"),
        avg_dead_air_rate_per_min=avg_f("summary.dead_air_rate_per_min", 2),
    )


@router.get("/recent")
async def recent_calls(limit: int = 10, user: CurrentUser = Depends(get_current_user)):
    """Last N calls for the dashboard recent-activity table."""
    col = reports_col()
    cursor = col.find(
        {"org_id": user.org_id},
        {"_id": 0, "call_id": 1, "generated_at": 1, "outcome": 1,
         "voicera_number": 1, "objective": 1, "_csat": 1, "language": 1,
         "connection": 1, "_duration_secs": 1, "judge": 1, "_eval_result": 1}
    ).sort("generated_at", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    for d in docs:
        d["csat"] = d.pop("_csat", None)
        d["duration_secs"] = d.pop("_duration_secs", None)
        d["eval_result"] = eval_result_from_doc(d)
    return docs
