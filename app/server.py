"""FastAPI app: trigger an outbound Vobiz call to a Voicera number and run the
evals (QA tester) agent over the resulting media WebSocket.

Flow:
  POST /api/evals-call {voicera_number}
    -> Vobiz /Call/  (from=caller id, to=voicera_number, answer_url=/answer?call_id=...)
    -> Vobiz dials Voicera (prod); Voicera answers + greets
    -> Vobiz POSTs /answer  -> we return Stream XML pointing at  /agent/{call_id}
    -> WS /agent/{call_id} runs the Pipecat tester pipeline
"""

import asyncio
import json
import os
import traceback
from uuid import uuid4

import requests
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel

from app import config
from app.auth import CurrentUser, get_current_user, get_optional_current_user
from app.bot import run_evals_bot
from app.library import (
    add_item,
    delete_item,
    list_all,
    merge_presets,
    resolve_library_paths_for_org,
    collect_library_ids_from_simulations,
    resolve_preview_path,
    resolve_path,
    org_key,
)


class EvalsCallRequest(BaseModel):
    voicera_number: str
    objective: str | None = None
    expected_outcome: str | None = None
    persona: str | None = None
    background_noise: str = "off"          # off | key in config.NOISE_FILES
    noise_volume: float | None = None      # 0.0–1.0 (defaults to config.NOISE_VOLUME)
    test_interruptions: bool = False       # barge in on Voicera to test interruption handling
    barge_in_style: str = "speech"         # speech | sound | both | speech_probes
    interrupt_after_secs: float | None = None
    language: str | None = None
    voicera_response_language: str | None = None  # language Voicera agent responds in (for STT)
    max_duration_minutes: int | None = None
    evals: object = "standard"             # preset string OR explicit list of metric keys
    # Structured simulation cases (UI-driven). See config.normalize_simulations for the shape.
    simulations: dict | None = None
    pulse_id: str | None = None            # set when this call was fired by the Pulse cron runner


# Per-call run config, set at POST time and read by the WebSocket handler (single process).
CALL_CONFIGS: dict[str, dict] = {}

# Tracks call_ids whose WebSocket pipeline is already live or completed, so Vobiz retried
# /answer webhooks don't spawn a second ghost pipeline on the same call.
ACTIVE_CALLS: set[str] = set()


def _build_stream_xml(websocket_url: str) -> str:
    """Vobiz XML telling it to stream call audio to our WebSocket."""
    if config.SAMPLE_RATE == 16000:
        content_type = "audio/x-l16;rate=16000"
    else:
        content_type = f"audio/x-mulaw;rate={config.SAMPLE_RATE}"

    logger.info(f"Returning Stream XML (contentType={content_type}) -> {websocket_url}")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true" contentType="{content_type}">
        {websocket_url}
    </Stream>
</Response>'''


def _resolve_https_base() -> str:
    """Public HTTPS base for Vobiz callbacks.

    Prefer the live ngrok tunnel (queried from ngrok's local API) so we never have to
    hand-edit PUBLIC_HTTPS_URL after an ngrok restart. Fall back to the env value.
    """
    for port in (4040, 4041):
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/api/tunnels", timeout=2)
            resp.raise_for_status()
            for tunnel in resp.json().get("tunnels", []):
                public_url = tunnel.get("public_url", "")
                if public_url.startswith("https"):
                    logger.info(f"Resolved public URL from ngrok (:{port}): {public_url}")
                    return public_url.rstrip("/")
        except Exception:
            continue
    return config.PUBLIC_HTTPS_URL


def make_outbound_call_vobiz(voicera_number: str, call_id: str) -> dict:
    """Place an outbound call to the Voicera number via Vobiz, using env creds."""
    https_base = _resolve_https_base()
    missing = [
        name
        for name, val in [
            ("VOBIZ_AUTH_ID", config.VOBIZ_AUTH_ID),
            ("VOBIZ_AUTH_TOKEN", config.VOBIZ_AUTH_TOKEN),
            ("VOBIZ_CALLER_ID", config.VOBIZ_CALLER_ID),
            ("PUBLIC_HTTPS_URL (no live ngrok tunnel found either)", https_base),
        ]
        if not val
    ]
    if missing:
        raise ValueError(f"Missing required config: {', '.join(missing)}")

    answer_url = f"{https_base}/answer?call_id={call_id}"
    headers = {
        "X-Auth-ID": config.VOBIZ_AUTH_ID,
        "X-Auth-Token": config.VOBIZ_AUTH_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {
        "from": config.VOBIZ_CALLER_ID,
        "to": voicera_number,
        "answer_url": answer_url,
        "answer_method": "POST",
    }

    url = f"{config.VOBIZ_API_BASE}/Account/{config.VOBIZ_AUTH_ID}/Call/"
    logger.info(f"📞 Outbound: {config.VOBIZ_CALLER_ID} → {voicera_number} (call_id={call_id})")
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    if not response.ok:
        # Surface Vobiz's actual rejection reason instead of a bare 400.
        logger.error(f"Vobiz {response.status_code} for to={voicera_number}: {response.text}")
        raise ValueError(f"Vobiz rejected the call ({response.status_code}): {response.text}")
    result = response.json()
    logger.info(f"✅ Call initiated: {result}")
    return result


# === FastAPI app ===

app = FastAPI(
    title="Evals Caller Server",
    description="Dials a Voicera number and runs an AI QA-tester agent over the call.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "healthy"}


def _builtin_noise_presets() -> list[dict]:
    return [
        {"id": key, "label": config.NOISE_LABELS.get(key, key.replace("_", " ").title())}
        for key in config.NOISE_FILES
    ]


def _builtin_interruption_presets() -> list[dict]:
    return [
        {"id": key, "label": config.INTERRUPTION_LABELS.get(key, key.replace("_", " ").title())}
        for key in config.INTERRUPTION_FILES
    ]


def _builtin_filler_presets() -> list[dict]:
    return [
        {"id": key, "label": config.CALLER_FILLER_LABELS.get(key, key.title())}
        for key in config.CALLER_FILLER_FILES
    ]


@app.get("/api/library")
async def library_list(user: CurrentUser = Depends(get_current_user)):
    """List the org's uploaded sounds grouped by category."""
    key = org_key(user.org_id)
    return {"items": list_all(key)}


@app.post("/api/library")
async def library_upload(
    category: str = Form(...),
    label: str = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    """Upload a named MP3 into ambient, barge_in, or other — shared across the org."""
    key = org_key(user.org_id)
    item = await add_item(key, category, label, file)
    return {"status": "ok", "item": item}


@app.delete("/api/library/{item_id}")
async def library_delete(item_id: str, user: CurrentUser = Depends(get_current_user)):
    key = org_key(user.org_id)
    delete_item(key, item_id)
    return {"status": "ok", "id": item_id}


@app.get("/api/library-preview/{item_id}")
async def library_preview(item_id: str, user: CurrentUser = Depends(get_current_user)):
    key = org_key(user.org_id)
    path = resolve_path(key, item_id)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown library sound: {item_id!r}")
    return FileResponse(path, media_type="audio/mpeg", filename=os.path.basename(path))


@app.get("/api/noise-presets")
async def noise_presets(user: CurrentUser | None = Depends(get_optional_current_user)):
    """Ambient noise options for the eval UI (id, label, preview duration)."""
    key = org_key(user.org_id) if user else None
    builtin = _builtin_noise_presets()
    return {
        "preview_secs": config.NOISE_PREVIEW_SECS,
        "presets": merge_presets(builtin, key, "ambient"),
    }


@app.get("/api/noise-preview/{preset}")
async def noise_preview(
    preset: str,
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    """Serve an ambient-noise MP3 for short UI previews."""
    key = org_key(user.org_id) if user else None
    path = resolve_preview_path(preset, config.NOISE_FILES, key)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown noise preset: {preset!r}")
    return FileResponse(path, media_type="audio/mpeg", filename=os.path.basename(path))


@app.get("/api/interruption-presets")
async def interruption_presets(user: CurrentUser | None = Depends(get_optional_current_user)):
    """Barge-in sound options from assets/interruptions/ plus the org's library."""
    key = org_key(user.org_id) if user else None
    builtin = _builtin_interruption_presets()
    return {
        "preview_secs": config.INTERRUPTION_PREVIEW_SECS,
        "presets": merge_presets(builtin, key, "barge_in"),
    }


@app.get("/api/interruption-preview/{preset}")
async def interruption_preview(
    preset: str,
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    """Serve a barge-in interruption MP3 for short UI previews."""
    key = org_key(user.org_id) if user else None
    path = resolve_preview_path(preset, config.INTERRUPTION_FILES, key)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown interruption preset: {preset!r}")
    return FileResponse(path, media_type="audio/mpeg", filename=os.path.basename(path))


@app.get("/api/filler-presets")
async def filler_presets(user: CurrentUser | None = Depends(get_optional_current_user)):
    """Built-in cough/hmm plus the org's Others library for caller reactions."""
    key = org_key(user.org_id) if user else None
    builtin = _builtin_filler_presets()
    return {
        "preview_secs": config.INTERRUPTION_PREVIEW_SECS,
        "presets": merge_presets(builtin, key, "other"),
    }


@app.get("/api/filler-preview/{kind}")
async def filler_preview(
    kind: str,
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    """Serve a caller-reaction MP3 (cough/hmm or library other) for short UI previews."""
    key = org_key(user.org_id) if user else None
    path = resolve_preview_path(kind, config.CALLER_FILLER_FILES, key)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown filler sound: {kind!r}")
    return FileResponse(path, media_type="audio/mpeg", filename=os.path.basename(path))


def _report_path(call_id: str) -> str:
    from app.report import REPORTS_DIR

    return os.path.join(REPORTS_DIR, f"report_{call_id}.json")


@app.get("/api/metrics/aggregate")
async def metrics_aggregate():
    """Scan persisted reports and return fleet-level connection rates."""
    from app.report import REPORTS_DIR

    connected = graceful = dropped = 0
    total = 0
    if os.path.isdir(REPORTS_DIR):
        for name in os.listdir(REPORTS_DIR):
            if not name.startswith("report_") or not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(REPORTS_DIR, name)) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            conn = data.get("connection") or {}
            total += 1
            if conn.get("connected"):
                connected += 1
            if conn.get("ended_gracefully"):
                graceful += 1
            if conn.get("dropped_midcall"):
                dropped += 1

    def rate(n):
        return round(n / total, 3) if total else None

    return {
        "n": total,
        "connection_success_rate": rate(connected),
        "graceful_termination_rate": rate(graceful),
        "mid_call_drop_rate": rate(dropped),
    }


@app.get("/api/report/{call_id}/status")
async def report_status(call_id: str):
    """Poll target: is the post-call report ready yet?"""
    return {"call_id": call_id, "ready": os.path.exists(_report_path(call_id))}


@app.get("/api/report/{call_id}")
async def report_data(call_id: str):
    """Serve the structured JSON report for the frontend to render natively."""
    path = _report_path(call_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not ready")
    return FileResponse(path, media_type="application/json")


@app.get("/api/report/{call_id}/recording")
async def report_recording(call_id: str):
    """Serve the call's WAV recording (referenced by the report's recording_url)."""
    from app.report import RECORDINGS_DIR

    path = os.path.join(RECORDINGS_DIR, f"{call_id}.wav")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Recording not available")
    return FileResponse(path, media_type="audio/wav", filename=f"{call_id}.wav")


@app.post("/api/evals-call")
async def evals_call(
    request: EvalsCallRequest,
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    voicera_number = (request.voicera_number or "").strip()
    if not voicera_number:
        raise HTTPException(status_code=400, detail="voicera_number is required")

    call_id = uuid4().hex
    run_config = {
        "call_id": call_id,       # stamped here so report_id in bot.py uses the UUID, not the Vobiz SID
        "voicera_number": voicera_number,
        "objective": request.objective or config.TEST_OBJECTIVE,
        "expected_outcome": request.expected_outcome
        or request.objective
        or config.TEST_OBJECTIVE,
        "persona": request.persona,
        "background_noise": (request.background_noise or "off").strip().lower(),
        "noise_volume": (
            config.NOISE_VOLUME
            if request.noise_volume is None
            else max(0.0, min(1.0, float(request.noise_volume)))
        ),
        "test_interruptions": bool(request.test_interruptions),
        "barge_in_style": (request.barge_in_style or "speech").strip().lower(),
        "interrupt_after_secs": request.interrupt_after_secs or config.INTERRUPT_AFTER_SECS,
        "language": request.language,
        "voicera_response_language": request.voicera_response_language or None,
        "max_duration_minutes": request.max_duration_minutes
        or config.SESSION_TIMEOUT_MINUTES,
        "evals": config.resolve_evals(request.evals),
        "simulations": config.normalize_simulations(request.simulations),
        "pulse_id": request.pulse_id,
        "org_id": user.org_id if user else None,
    }
    if user:
        lib_ids = collect_library_ids_from_simulations(run_config["simulations"])
        if lib_ids:
            run_config["library_paths"] = resolve_library_paths_for_org(user.org_id, lib_ids)
    CALL_CONFIGS[call_id] = run_config

    try:
        result = make_outbound_call_vobiz(voicera_number, call_id)
    except ValueError as e:
        CALL_CONFIGS.pop(call_id, None)
        logger.error(f"❌ Invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        CALL_CONFIGS.pop(call_id, None)
        logger.error(f"❌ Outbound call failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "call_id": call_id,
            "voicera_number": voicera_number,
            "run_config": {k: v for k, v in run_config.items() if k != "persona" or v},
            "vobiz_result": result,
        },
    )


@app.api_route("/answer", methods=["GET", "POST"], include_in_schema=False)
async def answer_webhook(request: Request):
    """Vobiz answer webhook for our outbound leg -> return Stream XML.

    The WS host is taken from the request's Host header (the host Vobiz just reached
    us on), so it always matches the live tunnel without depending on PUBLIC_WSS_URL.
    """
    call_id = request.query_params.get("call_id", "unknown")
    host = request.headers.get("host")
    wss_base = f"wss://{host}" if host else config.PUBLIC_WSS_URL
    if not wss_base:
        logger.error("No request Host and PUBLIC_WSS_URL not set; cannot build Stream XML")
        raise HTTPException(status_code=500, detail="Cannot resolve WebSocket URL")

    websocket_url = f"{wss_base}/agent/{call_id}"

    async def _ws_connection_timeout():
        await asyncio.sleep(30)
        if call_id not in ACTIVE_CALLS and call_id in CALL_CONFIGS:
            logger.warning(f"⚠️ WebSocket never opened for call_id={call_id}; writing failure report")
            run_config = CALL_CONFIGS.pop(call_id, {})
            run_config["call_id"] = call_id
            from app.report import write_failure_report
            write_failure_report(call_id, run_config, reason="never_connected")

    asyncio.create_task(_ws_connection_timeout())

    return Response(
        content=_build_stream_xml(websocket_url),
        media_type="application/xml",
    )


@app.websocket("/agent/{call_id}")
async def agent_websocket(websocket: WebSocket, call_id: str):
    """Media WebSocket: read the Vobiz start frame, then run the tester pipeline."""
    await websocket.accept()

    # Reject duplicate connections for the same call_id (Vobiz occasionally retries
    # the /answer webhook after the first pipeline ends, which would spawn a ghost
    # second bot and race with the first bot's report write).
    if call_id in ACTIVE_CALLS:
        logger.warning(f"⚠️ Duplicate WebSocket for call_id={call_id}; rejecting")
        await websocket.close(code=1008, reason="duplicate call_id")
        return
    ACTIVE_CALLS.add(call_id)
    logger.info(f"🔌 WebSocket connected: call_id={call_id}")

    run_config = CALL_CONFIGS.pop(call_id, {})
    run_config["call_id"] = call_id  # report is filed under the API-returned UUID
    stream_sid = call_id
    call_sid = call_id
    try:
        first_message = await websocket.receive_text()
        data = json.loads(first_message)
        if data.get("event") != "start":
            logger.warning(f"⚠️ Expected 'start' event, got: {data.get('event')}")
        start_info = data.get("start", {}) or {}
        call_sid = start_info.get("callSid") or start_info.get("callId") or call_id
        stream_sid = start_info.get("streamSid") or start_info.get("streamId") or call_id
        logger.info(f"📞 Call started: call_sid={call_sid}, stream_sid={stream_sid}")

        await run_evals_bot(websocket, stream_sid, call_sid, run_config)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        logger.debug(traceback.format_exc())
    finally:
        ACTIVE_CALLS.discard(call_id)
        logger.info(f"🔌 WebSocket closed: call_id={call_id}")
