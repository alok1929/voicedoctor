import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.database import pulses_col, reports_col
from app.models import PulseIn, PulseUpdate
from app.eval_result import eval_result_from_doc
from app.pulse_engine import fire_pulse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pulses", tags=["pulses"])

ALLOWED_INTERVALS = (15, 30, 60, 360, 1440)


def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    return doc


@router.post("", status_code=201)
async def create_pulse(pulse: PulseIn, user: CurrentUser = Depends(get_current_user)):
    if pulse.interval_minutes not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval_minutes must be one of {ALLOWED_INTERVALS}")
    if pulse.max_runs is not None and pulse.max_runs < 1:
        raise HTTPException(status_code=400, detail="max_runs must be at least 1")
    now = datetime.now(timezone.utc)
    doc = {
        "_id": uuid4().hex,
        "name": pulse.name.strip() or "Untitled pulse",
        "voicera_number": pulse.voicera_number.strip(),
        "objective": pulse.objective,
        "expected_outcome": pulse.expected_outcome,
        "persona": pulse.persona,
        "language": pulse.language,
        "evals": pulse.evals,
        "simulations": pulse.simulations or {},
        "interval_minutes": pulse.interval_minutes,
        "max_runs": pulse.max_runs,
        "run_count": 0,
        "enabled": True,
        "owner_email": user.email,
        "org_id": user.org_id,
        "created_at": now.isoformat(),
        "next_run_at": now.isoformat(),
        "last_run_at": None,
        "last_result": None,
    }
    await pulses_col().insert_one(doc)

    # Fire the first run immediately so the user sees a result right away instead of
    # waiting for the next cron tick. requests.post is blocking, so run it off the
    # event loop thread; evals-call itself just kicks off the outbound call and
    # returns fast (the actual conversation runs later over the WebSocket pipeline).
    try:
        result = await asyncio.to_thread(fire_pulse, doc)
    except Exception as e:
        result = {"status": "error", "detail": str(e)}
        logger.error(f"Immediate run of pulse {doc['_id']} failed: {e}")

    now2 = datetime.now(timezone.utc)
    run_count = 1
    maxed_out = pulse.max_runs is not None and run_count >= pulse.max_runs
    changes: dict = {
        "last_run_at": now2.isoformat(),
        "last_result": result,
        "run_count": run_count,
    }
    if maxed_out:
        changes["enabled"] = False
        changes["next_run_at"] = None
    else:
        # On success, arm the next scheduled run; on failure, leave it due so the cron
        # runner retries within a minute instead of waiting a full interval.
        changes["next_run_at"] = (
            (now2 + timedelta(minutes=pulse.interval_minutes)).isoformat()
            if result.get("status") == "started"
            else now2.isoformat()
        )
    await pulses_col().update_one({"_id": doc["_id"]}, {"$set": changes})
    doc.update(changes)
    return _serialize(doc)


@router.get("")
async def list_pulses(user: CurrentUser = Depends(get_current_user)):
    cursor = pulses_col().find({"org_id": user.org_id}).sort("created_at", -1)
    docs = await cursor.to_list(length=200)
    return [_serialize(d) for d in docs]


@router.patch("/{pulse_id}")
async def update_pulse(pulse_id: str, update: PulseUpdate, user: CurrentUser = Depends(get_current_user)):
    col = pulses_col()
    existing = await col.find_one({"_id": pulse_id, "org_id": user.org_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Pulse not found")

    raw = update.model_dump(exclude_unset=True)
    clear_max_runs = raw.pop("clear_max_runs", False)
    changes = {k: v for k, v in raw.items() if v is not None}
    if clear_max_runs:
        changes["max_runs"] = None
    if "max_runs" in changes and changes["max_runs"] is not None and changes["max_runs"] < 1:
        raise HTTPException(status_code=400, detail="max_runs must be at least 1")
    if "interval_minutes" in changes and changes["interval_minutes"] not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval_minutes must be one of {ALLOWED_INTERVALS}")
    if not changes:
        return _serialize(existing)

    # Re-arm the schedule immediately if the interval changed or it was just re-enabled.
    if "interval_minutes" in changes or changes.get("enabled") is True:
        changes["next_run_at"] = datetime.now(timezone.utc).isoformat()
        # Re-enabling a pulse that had already hit its run limit starts a fresh count.
        if changes.get("enabled") is True:
            existing_max = changes.get("max_runs", existing.get("max_runs"))
            if existing_max is not None and existing.get("run_count", 0) >= existing_max:
                changes["run_count"] = 0

    await col.update_one({"_id": pulse_id}, {"$set": changes})
    updated = await col.find_one({"_id": pulse_id})
    return _serialize(updated)


@router.delete("/{pulse_id}", status_code=204)
async def delete_pulse(pulse_id: str, user: CurrentUser = Depends(get_current_user)):
    result = await pulses_col().delete_one({"_id": pulse_id, "org_id": user.org_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pulse not found")


@router.get("/{pulse_id}/runs")
async def pulse_runs(pulse_id: str, limit: int = 20, user: CurrentUser = Depends(get_current_user)):
    pulse = await pulses_col().find_one({"_id": pulse_id, "org_id": user.org_id})
    if not pulse:
        raise HTTPException(status_code=404, detail="Pulse not found")
    cursor = (
        reports_col()
        .find({"pulse_id": pulse_id, "org_id": user.org_id}, {"_id": 0})
        .sort("generated_at", -1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [
        {
            "call_id": d.get("call_id"),
            "generated_at": d.get("generated_at"),
            "outcome": d.get("outcome"),
            "eval_result": eval_result_from_doc(d),
            "csat": d.get("_csat"),
        }
        for d in docs
    ]
