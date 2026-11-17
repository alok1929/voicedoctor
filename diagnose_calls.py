"""Diagnostic: compare what Vobiz does with the English vs Marathi outbound call.

Both calls are placed identically (same caller ID, same answer_url) — the only thing
that differs is the destination DID. We place a call to each, capture the initiate
response, then poll Vobiz for the live-call state and the CDR so we can see WHY one
connects and the other only ever sits "queued" (e.g. no-answer / busy / hangup cause).

Run:  .venv/bin/python diagnose_calls.py
"""

import json
import sys
import time

import requests

from app import config
from app.server import _resolve_https_base

EN = "+918065480891"
MR = "+918071387387"

HEADERS = {
    "X-Auth-ID": config.VOBIZ_AUTH_ID,
    "X-Auth-Token": config.VOBIZ_AUTH_TOKEN,
    "Content-Type": "application/json",
}
ACCOUNT_BASE = f"{config.VOBIZ_API_BASE}/Account/{config.VOBIZ_AUTH_ID}"


def _pp(label, resp):
    print(f"    {label}: HTTP {resp.status_code}")
    try:
        print("    " + json.dumps(resp.json(), indent=2).replace("\n", "\n    "))
    except Exception:
        body = resp.text.strip()
        if body:
            print("    " + body[:800].replace("\n", "\n    "))


def place_call(to_number, answer_url):
    payload = {
        "from": config.VOBIZ_CALLER_ID,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": "POST",
    }
    print(f"\n>>> Dialing {config.VOBIZ_CALLER_ID} -> {to_number}")
    print(f"    payload: {json.dumps(payload)}")
    resp = requests.post(f"{ACCOUNT_BASE}/Call/", json=payload, headers=HEADERS, timeout=30)
    _pp("initiate", resp)
    if not resp.ok:
        return None
    data = resp.json()
    # Vobiz/Plivo return request_uuid (queued) and later a call_uuid (live).
    return data.get("request_uuid") or data.get("call_uuid") or data.get("api_id")


def probe_status(uuid, to_number):
    """Try the Plivo-compatible live-call and CDR endpoints; print whatever we get."""
    if not uuid:
        print("    (no uuid returned; cannot poll status)")
        return
    # Live call detail (exists only while the call is up).
    for attempt in range(6):
        time.sleep(5)
        live = requests.get(f"{ACCOUNT_BASE}/Call/{uuid}/", headers=HEADERS, timeout=15)
        print(f"\n    [{to_number}] live poll #{attempt + 1} (uuid={uuid})")
        _pp("live", live)
        # Once the live endpoint 404s the call has ended -> look at the CDR.
        if live.status_code == 404:
            break
    # CDR / completed-call record (disposition, hangup cause, bill duration).
    cdr = requests.get(
        f"{ACCOUNT_BASE}/Call/", params={"limit": 5}, headers=HEADERS, timeout=15
    )
    print(f"\n    [{to_number}] recent CDRs")
    _pp("cdr-list", cdr)


def main():
    targets = {"MARATHI(working)": MR, "ENGLISH(broken)": EN}
    if len(sys.argv) > 1:  # allow: python diagnose_calls.py en|mr
        sel = sys.argv[1].lower()
        targets = {"ENGLISH": EN} if sel == "en" else {"MARATHI": MR}

    answer_url = f"{_resolve_https_base()}/answer?call_id=diag"
    print(f"Using answer_url: {answer_url}")
    print(f"Vobiz base: {ACCOUNT_BASE}")

    for label, number in targets.items():
        print("\n" + "=" * 70)
        print(label)
        print("=" * 70)
        uuid = place_call(number, answer_url)
        probe_status(uuid, number)


if __name__ == "__main__":
    main()
