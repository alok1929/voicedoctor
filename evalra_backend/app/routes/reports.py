from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user
from app.database import reports_col
from app.eval_result import eval_result_from_doc
from app.models import ReportIn, ReportListItem

router = APIRouter(prefix="/reports", tags=["reports"])


def simulation_summary(meta: dict) -> tuple[list[str], str | None]:
    """Which simulations ran on this call and the sound preset used, from the
    structured `simulations` block (with legacy flat-field fallback)."""
    sims = meta.get("simulations") or {}
    kinds: list[str] = []
    sound: str | None = None

    noise = sims.get("ambient_noise") or {}
    if noise.get("enabled"):
        kinds.append("ambient_noise")
        sound = noise.get("type") or None

    barge = sims.get("barge_in") or {}
    if barge.get("enabled"):
        kinds.append("barge_in")
        if sound is None and barge.get("style") in ("sound", "both"):
            sound = barge.get("sound_type") or None

    lang = sims.get("language_switch") or {}
    if lang.get("enabled"):
        kinds.append("language_switch")

    if not kinds:
        bg = (meta.get("background_noise") or "").strip().lower()
        if bg and bg != "off":
            kinds.append("ambient_noise")
            sound = bg
        if meta.get("test_interruptions"):
            kinds.append("barge_in")

    return kinds, sound


@router.post("", status_code=201)
async def ingest_report(report: ReportIn):
    """Called by evals_caller_server after each call (server-to-server, no user JWT —
    the org_id it carries was already resolved from the caller's token at call time
    and threaded through via meta). Upserts by call_id."""
    col = reports_col()
    doc = report.model_dump()
    # Flatten meta fields to top-level for easy querying
    meta = doc.get("meta") or {}
    doc["voicera_number"] = meta.get("voicera_number") or doc.get("voicera_number") or ""
    doc["objective"] = meta.get("objective") or ""
    doc["language"] = meta.get("language") or "en"
    doc["pulse_id"] = meta.get("pulse_id") or doc.get("pulse_id") or None
    doc["org_id"] = meta.get("org_id") or doc.get("org_id") or None
    # Flatten CSAT from judge for quick aggregate queries
    judge = doc.get("judge") or {}
    doc["_csat"] = judge.get("csat")
    eo = judge.get("metrics", {}).get("expected_outcome")
    if isinstance(eo, dict):
        doc["_eval_result"] = eo.get("value")
    # Flatten duration from summary
    summary = doc.get("summary") or {}
    doc["_duration_secs"] = summary.get("duration_secs")
    doc["_voicera_wpm"] = summary.get("voicera_wpm")

    await col.update_one(
        {"call_id": report.call_id},
        {"$set": doc},
        upsert=True,
    )
    return {"status": "stored", "call_id": report.call_id}


@router.get("", response_model=list[ReportListItem])
async def list_reports(
    voicera_number: str | None = None,
    outcome: str | None = None,
    language: str | None = None,
    limit: int = Query(50, le=200),
    skip: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    col = reports_col()
    filt: dict = {"org_id": user.org_id}
    if voicera_number:
        filt["voicera_number"] = voicera_number
    if outcome:
        filt["outcome"] = outcome
    if language:
        filt["language"] = language

    cursor = col.find(filt, {"_id": 0}).sort("generated_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)

    items = []
    for d in docs:
        sim_kinds, sim_sound = simulation_summary(d.get("meta") or {})
        items.append(
            ReportListItem(
                call_id=d["call_id"],
                generated_at=d.get("generated_at", ""),
                outcome=d.get("outcome", "unknown"),
                eval_result=eval_result_from_doc(d),
                voicera_number=d.get("voicera_number", ""),
                objective=d.get("objective", ""),
                csat=d.get("_csat"),
                language=d.get("language", "en"),
                simulations=sim_kinds,
                simulation_sound=sim_sound,
            )
        )
    return items


@router.get("/{call_id}")
async def get_report(call_id: str, user: CurrentUser = Depends(get_current_user)):
    col = reports_col()
    doc = await col.find_one({"call_id": call_id, "org_id": user.org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Report not found")
    return doc


@router.delete("/{call_id}", status_code=204)
async def delete_report(call_id: str, user: CurrentUser = Depends(get_current_user)):
    col = reports_col()
    result = await col.delete_one({"call_id": call_id, "org_id": user.org_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Report not found")
