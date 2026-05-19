"""In-process job scheduler for Droply.

Registered jobs (all run inside the FastAPI event loop):

  * order_sync       — every  10 min · POST /api/orders/sync
  * tracking_refresh — every  30 min · POST /api/orders/refresh-all-tracking
  * message_flush    — every   1 min · POST /api/messages/outbound/flush

Each job no-ops when the global toggle `scheduler_enabled` (in `app_settings`)
is false, or when the underlying call needs an eBay account that isn't
connected yet — failures are logged but never propagate, so one broken tenant
state can't kill the loop.

An Amazon price/stock poll job is intentionally omitted: the project does not
yet have a server-side scraper, so polling lives in the Chrome extension's
background recheck (chrome.alarms). Roadmap Phase 4 swaps that in.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("droply.scheduler")

_scheduler: Optional[AsyncIOScheduler] = None
_last_runs: dict[str, dict[str, Any]] = {}


def _enabled() -> bool:
    # Local import to avoid the scheduler ↔ main import cycle at module load.
    from backend.main import get_settings_dict
    return (get_settings_dict().get("scheduler_enabled", "true").lower() == "true")


def _record(job_id: str, result: dict[str, Any] | None, error: str | None) -> None:
    import datetime as _dt
    _last_runs[job_id] = {
        "ran_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "result": result,
        "error": error,
    }


async def _job_order_sync() -> None:
    if not _enabled():
        return
    from backend.main import sync_orders
    try:
        result = await sync_orders(limit=50)
        _record("order_sync", result, None)
    except Exception as e:  # noqa: BLE001 — log and move on
        _record("order_sync", None, str(e)[:300])
        logger.warning("order_sync failed: %s", e)


async def _job_tracking_refresh() -> None:
    if not _enabled():
        return
    from backend.main import refresh_all_tracking
    try:
        result = await refresh_all_tracking()
        _record("tracking_refresh", result, None)
    except Exception as e:  # noqa: BLE001
        _record("tracking_refresh", None, str(e)[:300])
        logger.warning("tracking_refresh failed: %s", e)


async def _job_message_flush() -> None:
    if not _enabled():
        return
    from backend.main import flush_outbound_messages
    try:
        result = await flush_outbound_messages(limit=50)
        _record("message_flush", result, None)
    except Exception as e:  # noqa: BLE001
        _record("message_flush", None, str(e)[:300])
        logger.warning("message_flush failed: %s", e)


async def _job_inbox_poll() -> None:
    """Phase 4.1 — pull new buyer messages from Trading GetMyMessages."""
    if not _enabled():
        return
    from backend.main import poll_inbound_for_all_accounts
    try:
        result = await poll_inbound_for_all_accounts(lookback_days=7)
        _record("inbox_poll", result, None)
    except Exception as e:  # noqa: BLE001
        _record("inbox_poll", None, str(e)[:300])
        logger.warning("inbox_poll failed: %s", e)


async def _job_feedback_followup() -> None:
    """Phase 3.4 — queue feedback_request templates N days post-delivery."""
    if not _enabled():
        return
    from backend.main import queue_overdue_feedback_requests
    try:
        result = queue_overdue_feedback_requests()
        _record("feedback_followup", result, None)
    except Exception as e:  # noqa: BLE001
        _record("feedback_followup", None, str(e)[:300])
        logger.warning("feedback_followup failed: %s", e)


def start() -> None:
    """Idempotent: safe to call multiple times (replaces existing jobs)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        _job_message_flush, IntervalTrigger(minutes=1),
        id="message_flush", replace_existing=True, max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _job_inbox_poll, IntervalTrigger(minutes=5),
        id="inbox_poll", replace_existing=True, max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _job_order_sync, IntervalTrigger(minutes=10),
        id="order_sync", replace_existing=True, max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _job_tracking_refresh, IntervalTrigger(minutes=30),
        id="tracking_refresh", replace_existing=True, max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _job_feedback_followup, IntervalTrigger(hours=6),
        id="feedback_followup", replace_existing=True, max_instances=1,
        coalesce=True,
    )

    if not _scheduler.running:
        _scheduler.start()
    logger.info("Droply scheduler started (5 jobs).")


def shutdown() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    logger.info("Droply scheduler stopped.")


def status() -> dict[str, Any]:
    """Snapshot for the /api/scheduler/status endpoint."""
    running = bool(_scheduler and _scheduler.running)
    jobs = []
    if _scheduler:
        for j in _scheduler.get_jobs():
            jobs.append({
                "id": j.id,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                "trigger": str(j.trigger),
                "last_run": _last_runs.get(j.id),
            })
    return {
        "running": running,
        "enabled": _enabled(),
        "jobs": jobs,
    }
