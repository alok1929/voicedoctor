"""One-time migration: recompute interruption-scoring summary fields from each
report's stored ledger.

app/metrics.py's summary() previously only scored "real_bargein"/"fake_noise"
events toward interruption_detection_accuracy/false_interruption_rate, and
folded filler_cough into speech_probe_accuracy under a probe-labeled metric.
Any report whose ledger contains caller_hmm/filler_speech/filler_cough events
therefore has a summary that silently ignores or mislabels those failures
even though the ledger itself already has the correct per-event `correct`/
`reacted` flags. This script recomputes only the affected summary fields —
interruption_detection_accuracy, false_interruption_rate, noise_events,
noise_false_stops, and the speech_probe_* fields — from each report's stored
ledger, in place, leaving everything else in summary untouched.

Usage:
    .venv/bin/python backfill_interruption_metrics.py [--dry-run]
"""

import asyncio
import sys

from app.database import close_client, reports_col

EV_REAL_BARGEIN = "real_bargein"
EV_FAKE_NOISE = "fake_noise"
EV_PROBE_STOP = "probe_stop"
EV_PROBE_START = "probe_start"
EV_FILLER_SPEECH = "filler_speech"
EV_FILLER_COUGH = "filler_cough"
EV_CALLER_HMM = "caller_hmm"


def _rate(numer: int, denom: int):
    return round(numer / denom, 3) if denom else None


def _avg(xs: list[float]):
    return sum(xs) / len(xs) if xs else None


def recompute_interruption_summary(ledger: list[dict]) -> dict:
    """Rebuild the interruption/speech-probe summary fields from a stored ledger."""
    by_kind = {}
    for e in ledger or []:
        by_kind.setdefault(e.get("kind"), []).append(e)

    real = by_kind.get(EV_REAL_BARGEIN, [])
    fake = by_kind.get(EV_FAKE_NOISE, [])
    probe_stop = by_kind.get(EV_PROBE_STOP, [])
    probe_start = by_kind.get(EV_PROBE_START, [])
    filler_speech = by_kind.get(EV_FILLER_SPEECH, [])
    filler_cough = by_kind.get(EV_FILLER_COUGH, [])
    caller_hmm = by_kind.get(EV_CALLER_HMM, [])

    noise = fake + filler_speech + filler_cough + caller_hmm
    noise_stopped = [e for e in noise if e.get("reacted")]
    scored = real + noise

    probe_scored = probe_stop + probe_start
    probe_stop_lat = [
        e["interruption_response_latency_s"]
        for e in probe_stop
        if e.get("interruption_response_latency_s") is not None
    ]
    probe_start_lat = [
        e["interruption_response_latency_s"]
        for e in probe_start
        if e.get("interruption_response_latency_s") is not None
    ]
    filler_hmm = filler_speech + caller_hmm
    filler_false = [e for e in filler_hmm if e.get("reacted")]
    cough_false = [e for e in filler_cough if e.get("reacted")]

    return {
        "interruption_detection_accuracy": (
            _rate(sum(1 for e in scored if e.get("correct")), len(scored)) if scored else None
        ),
        "false_interruption_rate": (
            _rate(len(noise_stopped), len(noise)) if noise else None
        ),
        "noise_events": len(noise),
        "noise_false_stops": len(noise_stopped),
        "speech_probe_stop_response_latency_s": _avg(probe_stop_lat),
        "speech_probe_start_response_latency_s": _avg(probe_start_lat),
        "speech_probe_stop_correct": (
            all(e.get("correct") for e in probe_stop) if probe_stop else None
        ),
        "speech_probe_start_correct": (
            all(e.get("correct") for e in probe_start) if probe_start else None
        ),
        "speech_probe_filler_events": len(filler_hmm) if filler_hmm else None,
        "speech_probe_filler_false_stops": len(filler_false) if filler_hmm else None,
        "speech_probe_filler_false_stop_rate": (
            _rate(len(filler_false), len(filler_hmm)) if filler_hmm else None
        ),
        "speech_probe_cough_false_stop": (
            len(cough_false) > 0 if filler_cough else None
        ),
        "speech_probe_cough_false_stop_rate": (
            _rate(len(cough_false), len(filler_cough)) if filler_cough else None
        ),
        "speech_probe_cough_correct": (
            all(e.get("correct") for e in filler_cough) if filler_cough else None
        ),
        "speech_probe_accuracy": (
            _rate(sum(1 for e in probe_scored if e.get("correct")), len(probe_scored))
            if probe_scored
            else None
        ),
    }


async def main():
    dry_run = "--dry-run" in sys.argv[1:]

    reports = reports_col()
    cursor = reports.find({"ledger": {"$exists": True, "$ne": []}})

    scanned = 0
    changed = 0
    async for doc in cursor:
        scanned += 1
        old_summary = doc.get("summary") or {}
        new_fields = recompute_interruption_summary(doc.get("ledger") or [])

        diff = {k: v for k, v in new_fields.items() if old_summary.get(k) != v}
        if not diff:
            continue

        changed += 1
        call_id = doc.get("call_id") or str(doc.get("_id"))
        print(f"{call_id}: {diff}")

        if not dry_run:
            await reports.update_one(
                {"_id": doc["_id"]},
                {"$set": {f"summary.{k}": v for k, v in new_fields.items()}},
            )

    mode = "DRY RUN — no writes made" if dry_run else "applied"
    print(f"\nScanned {scanned} reports with a ledger; {changed} needed changes ({mode}).")

    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
