"""
The daily register: one record per worker per date.

A day can be started by the worker on WhatsApp (check-in, or sending a work
photo) or by the supervisor on the dashboard. The worker can only ever
*claim* (check in, claim OT hours); status, OT hours and advances that count
for pay are set by the supervisor, who has the final say.

Rates are copied onto the day when it's created, so changing a worker's
rate later doesn't silently re-price days already worked.

Once a day is included in an approved pay run it is locked (`pay_run_id`
set) and can no longer be edited. That's what stops a day being paid twice.
"""

from datetime import date as date_cls, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import config
from accounts import AccountError, get_worker, now
from db import get_db
from payroll import MAX_OT_HOURS, STATUSES

REVIEW_STATES = ("pending", "accepted", "needs_photo")


class LockedError(AccountError):
    pass


def today() -> str:
    return datetime.now(ZoneInfo(config.SITE_TIMEZONE)).date().isoformat()


def parse_date(value: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise AccountError("Dates must look like 2025-11-09")


def date_range(start: str, end: str, max_days: int = 62) -> List[str]:
    s, e = date_cls.fromisoformat(parse_date(start)), date_cls.fromisoformat(parse_date(end))
    if e < s:
        raise AccountError("End date is before start date")
    if (e - s).days >= max_days:
        raise AccountError(f"Pick a period of at most {max_days} days")
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


def _public(doc):
    return {k: v for k, v in doc.items() if k != "_id"} if doc else None


def get_day(worker_id: str, day: str) -> Optional[dict]:
    return _public(get_db().attendance.find_one({"worker_id": worker_id, "date": day}))


def _new_day(worker: dict, day: str, source: str) -> dict:
    return {
        "worker_id": worker["worker_id"],
        "supervisor_id": worker["supervisor_id"],
        "site_id": worker["site_id"],
        "date": day,
        "status": "P",
        "ot_hours": 0,
        "ot_claim_hours": 0,
        "advance": 0,
        "notes": "",
        "daily_rate": worker.get("daily_rate", 0),
        "ot_rate": worker.get("ot_rate", 0),
        "source": source,
        "review": "pending",
        "check_in_at": None,
        "check_in_location": None,
        "pay_run_id": None,
        "created_at": now(),
        "updated_at": now(),
    }


def worker_check_in(worker: dict, day: Optional[str] = None, location: Optional[dict] = None,
                    photo_evidence_id: Optional[str] = None) -> dict:
    """Record a completed WhatsApp check-in (the bot only calls this once it
    has BOTH a location and a photo). Creates the day as Present if it doesn't
    exist; never overrides a status the supervisor already set.
    Returns {"day": ..., "created": bool}."""
    day = day or today()
    db = get_db()
    existing = db.attendance.find_one({"worker_id": worker["worker_id"], "date": day})
    if existing:
        update = {"updated_at": now()}
        if not existing.get("check_in_at"):
            update["check_in_at"] = now()
        if location:
            update["check_in_location"] = location
        if photo_evidence_id:
            update["check_in_photo"] = photo_evidence_id
        db.attendance.update_one({"_id": existing["_id"]}, {"$set": update})
        return {"day": get_day(worker["worker_id"], day), "created": False}

    doc = _new_day(worker, day, "whatsapp")
    doc["check_in_at"] = now()
    doc["check_in_location"] = location
    doc["check_in_photo"] = photo_evidence_id
    db.attendance.insert_one(doc)
    return {"day": _public(doc), "created": True}


def is_checked_in(worker_id: str, day: str) -> bool:
    """True once the worker completed check-in today, or the supervisor
    logged the day on the dashboard."""
    return get_db().attendance.count_documents({"worker_id": worker_id, "date": day}) > 0


def has_check_in_proof(worker_id: str, day: str) -> bool:
    """True only when the worker's WhatsApp check-in for the day has BOTH a
    shared location and a check-in photo. A day the supervisor logged on the
    dashboard (or an older record without proof) does not count."""
    return get_db().attendance.count_documents({
        "worker_id": worker_id, "date": day,
        "check_in_location": {"$nin": [None, {}]}, "check_in_photo": {"$nin": [None, ""]},
    }) > 0


def worker_claim_ot(worker: dict, hours: float, day: Optional[str] = None) -> Optional[dict]:
    """The worker claims overtime on a day they've checked in. Recorded as a
    claim the supervisor sees; it does not change pay until the supervisor
    sets OT hours. Returns None if they haven't checked in today."""
    hours = max(0.0, min(float(hours), MAX_OT_HOURS))
    day = day or today()
    result = get_db().attendance.update_one(
        {"worker_id": worker["worker_id"], "date": day},
        {"$set": {"ot_claim_hours": hours, "updated_at": now()}},
    )
    return get_day(worker["worker_id"], day) if result.matched_count else None


def supervisor_set_day(supervisor_id: str, worker_id: str, day: str, fields: dict) -> dict:
    """Create or edit one register line. Raises LockedError for a paid day."""
    day = parse_date(day)
    worker = get_worker(supervisor_id, worker_id)
    if not worker:
        raise AccountError("Worker not found")

    update: Dict = {}
    if "status" in fields and fields["status"] is not None:
        status = str(fields["status"]).upper()
        if status not in STATUSES:
            raise AccountError(f"Status must be one of {', '.join(STATUSES)}")
        update["status"] = status
    if "ot_hours" in fields and fields["ot_hours"] is not None:
        ot = float(fields["ot_hours"])
        if not 0 <= ot <= MAX_OT_HOURS:
            raise AccountError(f"OT hours must be between 0 and {MAX_OT_HOURS}")
        update["ot_hours"] = ot
    if "advance" in fields and fields["advance"] is not None:
        adv = int(fields["advance"])
        if adv < 0:
            raise AccountError("Advance can't be negative")
        update["advance"] = adv
    if "notes" in fields and fields["notes"] is not None:
        update["notes"] = str(fields["notes"])[:300]
    if "review" in fields and fields["review"] is not None:
        if fields["review"] not in REVIEW_STATES:
            raise AccountError("Unknown review state")
        update["review"] = fields["review"]

    db = get_db()
    existing = db.attendance.find_one({"worker_id": worker_id, "date": day})
    if existing and existing.get("pay_run_id"):
        raise LockedError(f"{day} for {worker['name']} is already in pay run "
                          f"{existing['pay_run_id']} and can't be changed")

    # Entering OT hours on a plain Present day makes it an OT day, so the
    # register code matches what's being paid.
    resulting_status = update.get("status", (existing or {}).get("status", "P"))
    if update.get("ot_hours", 0) > 0 and resulting_status == "P":
        update["status"] = "OT"

    if existing:
        update["updated_at"] = now()
        db.attendance.update_one({"_id": existing["_id"]}, {"$set": update})
    else:
        doc = _new_day(worker, day, "dashboard")
        doc.update(update)
        db.attendance.insert_one(doc)
    return get_day(worker_id, day)


def days_for_site(supervisor_id: str, site_id: str, days: List[str]) -> List[dict]:
    cursor = get_db().attendance.find({
        "supervisor_id": supervisor_id, "site_id": site_id, "date": {"$in": days},
    })
    return [_public(d) for d in cursor]


def days_for_worker(worker_id: str, days: List[str]) -> List[dict]:
    return [_public(d) for d in get_db().attendance.find({"worker_id": worker_id, "date": {"$in": days}})]
