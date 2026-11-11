"""
Crew schedule: the supervisor plans who works which future day (with an
optional task and start time) on the Site calendar, and each scheduled
worker gets a WhatsApp message about it.

One shift per worker per date. A shift is a plan, not attendance: pay
still comes only from the register (check-in with location + photo, then
supervisor approval). Shifts are stored separately so planning never
touches pay.
"""

from datetime import date as date_cls
from typing import List, Optional

from accounts import AccountError, get_site, get_worker, now
from attendance import date_range, parse_date, today
from db import get_db

MAX_DAYS = 14


def _public(doc):
    return {k: v for k, v in doc.items() if k != "_id"} if doc else None


def _fmt(iso: str) -> str:
    d = date_cls.fromisoformat(iso)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def _span_label(dates: List[str]) -> str:
    return _fmt(dates[0]) if len(dates) == 1 else f"{_fmt(dates[0])} – {_fmt(dates[-1])}"


def create(supervisor_id: str, site_id: str, worker_id: str, start: str, end: str,
           task: str = "", start_time: str = "") -> dict:
    """Schedule a worker for every day from start to end. Returns
    {"shifts": [...], "dates": [...], "worker": ..., "site": ...}."""
    site = get_site(supervisor_id, site_id)
    worker = get_worker(supervisor_id, worker_id)
    if not site or not worker or worker["site_id"] != site_id:
        raise AccountError("Worker not found on this site")
    start, end = parse_date(start), parse_date(end)
    if start < today():
        raise AccountError("You can only schedule today or future days")
    dates = date_range(start, end, max_days=MAX_DAYS)
    task = (task or "").strip()[:120]
    start_time = (start_time or "").strip()[:10]

    db = get_db()
    for d in dates:
        db.shifts.update_one(
            {"worker_id": worker_id, "date": d},
            {"$set": {"supervisor_id": supervisor_id, "site_id": site_id, "task": task,
                      "start_time": start_time, "updated_at": now()},
             "$setOnInsert": {"created_at": now(), "notified": False}},
            upsert=True,
        )
    shifts = [_public(s) for s in db.shifts.find({"worker_id": worker_id, "date": {"$in": dates}})]
    return {"shifts": shifts, "dates": dates, "worker": worker, "site": site}


def delete(supervisor_id: str, worker_id: str, day: str) -> Optional[dict]:
    db = get_db()
    doc = db.shifts.find_one_and_delete({"supervisor_id": supervisor_id, "worker_id": worker_id,
                                        "date": parse_date(day)})
    return _public(doc)


def for_site(supervisor_id: str, site_id: str, days: List[str]) -> List[dict]:
    return [_public(s) for s in get_db().shifts.find(
        {"supervisor_id": supervisor_id, "site_id": site_id, "date": {"$in": days}})]


def mark_notified(worker_id: str, dates: List[str]) -> None:
    get_db().shifts.update_many({"worker_id": worker_id, "date": {"$in": dates}},
                                {"$set": {"notified": True, "notified_at": now()}})


def message_for(worker: dict, site: dict, dates: List[str], task: str, start_time: str) -> str:
    first = worker["name"].split()[0]
    lines = [
        "📅 *SitePay: you've been scheduled*",
        "",
        f"Hello {first}, you're on the crew at *{site['name']}*"
        + (f" ({site['location']})" if site.get("location") else "") + ".",
        f"🗓️ {_span_label(dates)}" + (f" ({len(dates)} days)" if len(dates) > 1 else ""),
    ]
    if start_time:
        lines.append(f"⏰ Start: {start_time}")
    if task:
        lines.append(f"🔨 Task: {task}")
    lines += [
        "",
        "When you arrive, tap *✅ Check in* here and share your location and a photo from the site.",
    ]
    return "\n".join(lines)


def cancel_message(worker: dict, site: dict, day: str) -> str:
    return (f"📅 *SitePay: schedule change*\n\nHello {worker['name'].split()[0]}, you're no longer "
            f"scheduled at *{site['name']}* on {_fmt(day)}.")
