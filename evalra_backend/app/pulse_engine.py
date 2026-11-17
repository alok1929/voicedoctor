"""Shared logic for firing a Pulse against evals_caller_server.

Used by both the API (to run a pulse immediately on creation) and pulse_runner.py
(the cron script that fires pulses on their configured interval).
"""

import os
from datetime import datetime, timedelta, timezone

import requests
from jose import jwt

from app.config import settings

EVALS_CALLER_URL = os.getenv("EVALS_CALLER_URL", "http://localhost:7870").rstrip("/")
SERVICE_TOKEN_TTL_MINUTES = 10


def service_token(email: str, org_id: str) -> str:
    """Self-mint a short-lived JWT for the pulse owner — no stored session token needed."""
    payload = {
        "sub": email,
        "org_id": org_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=SERVICE_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def fire_pulse(pulse: dict) -> dict:
    token = service_token(pulse["owner_email"], pulse["org_id"])
    body = {
        "voicera_number": pulse["voicera_number"],
        "objective": pulse.get("objective"),
        "expected_outcome": pulse.get("expected_outcome"),
        "persona": pulse.get("persona"),
        "language": pulse.get("language"),
        "evals": pulse.get("evals") or "standard",
        "simulations": pulse.get("simulations") or {},
        "pulse_id": pulse["_id"],
    }
    resp = requests.post(
        f"{EVALS_CALLER_URL}/api/evals-call",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if not resp.ok:
        return {"status": "error", "detail": resp.text[:300]}
    data = resp.json()
    return {"status": "started", "call_id": data.get("call_id")}
