"""One-time migration: attach all pre-existing data to a single org.

Org-scoping didn't exist before this change, so every report, pulse, and uploaded
library sound in the system today has no owner. This script:

  1. Ensures the given user (default: alok@framewise.ai) has an org — creating one
     if they don't already have one.
  2. Stamps that org_id onto every existing report and pulse (unconditionally —
     nothing has an org_id yet, so this is a one-shot, not an incremental backfill).
  3. Remaps that user's personal library directory (if any sounds were uploaded
     under the old per-email key) to the new org-keyed directory.

New signups after this point each get their own fresh org automatically (see
routes/auth.py) — this script only exists to seed the one org that inherits
everything that existed before org support did.

Usage:
    .venv/bin/python backfill_org.py [email]
"""

import asyncio
import hashlib
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from app.database import close_client, orgs_col, pulses_col, reports_col, users_col

DEFAULT_EMAIL = "alok@framewise.ai"

# Mirrors evals_caller_server/app/library.py's LIBRARY_ROOT — this script lives one
# directory below evals_caller_server, so the assets folder is a sibling of evalra_backend.
LIBRARY_ROOT = os.path.join(os.path.dirname(__file__), "..", "assets", "library", "users")


def _legacy_user_key(email: str) -> str:
    """Reproduces the old per-email library key (app/library.py's former user_key)."""
    normalized = (email or "").strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _org_key(org_id: str) -> str:
    normalized = (org_id or "").strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


async def main():
    email = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL).strip().lower()

    users = users_col()
    user = await users.find_one({"email": email})
    if not user:
        print(f"No user found for {email!r} — sign up with that email first, then re-run this script.")
        return

    org_id = user.get("org_id")
    if org_id:
        print(f"{email} already has org_id={org_id}; reusing it.")
    else:
        org_id = uuid4().hex
        await orgs_col().insert_one({
            "_id": org_id,
            "name": f"{user['name']}'s org",
            "created_at": datetime.now(timezone.utc),
        })
        await users.update_one({"email": email}, {"$set": {"org_id": org_id}})
        print(f"Created org {org_id} for {email}.")

    reports_result = await reports_col().update_many({}, {"$set": {"org_id": org_id}})
    print(f"Reports updated: {reports_result.modified_count}")

    pulses_result = await pulses_col().update_many({}, {"$set": {"org_id": org_id}})
    print(f"Pulses updated: {pulses_result.modified_count}")

    old_key = _legacy_user_key(email)
    new_key = _org_key(org_id)
    old_dir = os.path.join(LIBRARY_ROOT, old_key)
    new_dir = os.path.join(LIBRARY_ROOT, new_key)
    if os.path.isdir(old_dir) and not os.path.isdir(new_dir):
        os.makedirs(os.path.dirname(new_dir), exist_ok=True)
        os.rename(old_dir, new_dir)
        print(f"Library sounds remapped: {old_dir} -> {new_dir}")
    elif os.path.isdir(old_dir):
        print(f"Skipped library remap — {new_dir} already exists.")
    else:
        print("No existing per-user library directory found — nothing to remap.")

    print(f"\nDone. org_id = {org_id}")

    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
