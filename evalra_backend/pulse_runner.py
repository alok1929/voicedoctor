"""Pulse cron runner.

Fires due Pulses (recurring eval tests configured on the /pulse page) against the
evals_caller_server. Meant to be invoked by a real OS cron entry every minute —
each tick is a short-lived process, not a long-running scheduler:

    * * * * * cd /path/to/evalra_backend && .venv/bin/python pulse_runner.py >> pulse_runner.log 2>&1

A pulse's first run fires immediately from the API when it's created (see
routes/pulses.py); this runner only handles the recurring runs after that.

Idempotent: a pulse is only fired once its `next_run_at` has passed, and claiming
a due pulse (pushing next_run_at forward) happens atomically via find_one_and_update
so an overlapping tick (e.g. a slow run bleeding into the next minute) can't double-fire it.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.database import close_client, pulses_col
from app.pulse_engine import fire_pulse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_once():
    now = datetime.now(timezone.utc)
    col = pulses_col()
    due_cursor = col.find({"enabled": True, "next_run_at": {"$lte": now.isoformat()}})
    due = await due_cursor.to_list(length=200)

    for pulse in due:
        # Atomic claim: only proceed if next_run_at hasn't been pushed forward already
        # by a concurrent tick (e.g. a previous invocation still finishing up).
        claimed = await col.find_one_and_update(
            {"_id": pulse["_id"], "next_run_at": pulse["next_run_at"]},
            {"$set": {"next_run_at": (now + timedelta(minutes=pulse["interval_minutes"])).isoformat()}},
        )
        if not claimed:
            continue  # lost the race to another tick

        logger.info(f"🫀 Firing pulse {pulse['_id']} ({pulse['name']}) -> {pulse['voicera_number']}")
        try:
            result = fire_pulse(pulse)
        except Exception as e:
            result = {"status": "error", "detail": str(e)}
            logger.error(f"Pulse {pulse['_id']} failed: {e}")

        run_count = pulse.get("run_count", 0) + 1
        max_runs = pulse.get("max_runs")
        update_fields = {"last_run_at": now.isoformat(), "last_result": result, "run_count": run_count}
        if max_runs is not None and run_count >= max_runs:
            update_fields["enabled"] = False
            logger.info(f"🛑 Pulse {pulse['_id']} reached its run limit ({max_runs}); disabling")

        await col.update_one({"_id": pulse["_id"]}, {"$set": update_fields})


async def main():
    try:
        await run_once()
    finally:
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())
