"""
The AI check for one worker-day: a short checklist the supervisor reads
before accepting the day or paying it.

    ✅ Location shared                       (from the WhatsApp check-in)
    ✅ Check-in photo                        (from the WhatsApp check-in)
    ✅ Worker visible in check-in photo      (AI)
    ✅ Check-in photo taken on a work site   (AI)
    ✅ Photo date stamp matches the day      (AI, only if a stamp is printed)
    ✅ Work photo sent
    ✅ Work visible in work photo            (AI)
    ✅ Fresh photos (not reused)             (duplicate check)

The verdict is one of:

    verified     every item passed
    issues       at least one item failed (the failed items are listed)
    pending      the AI is still reading a photo
    unavailable  the AI could not read the photos (supervisor checks by eye)
    no_proof     on the register but no location and no check-in photo
    manual       logged by the supervisor on the dashboard, no WhatsApp proof
    absent       marked absent; nothing to check

The AI never accepts a day or moves money. The supervisor reads this and
decides; when they accept a day, the verdict at that moment is saved with it.
"""

from collections import Counter
from typing import Dict, List, Optional, Tuple
import os

import attendance
import evidence

# A check-in photo stamped after this time counts as late.
LATE_AFTER = os.getenv("CHECK_IN_LATE_AFTER", "08:30")

STATE_LABELS = {
    "verified": "AI verified",
    "issues": "AI found issues",
    "pending": "AI checking",
    "unavailable": "AI unavailable",
    "no_proof": "No check-in proof",
    "manual": "Logged by supervisor",
    "absent": "Absent",
}


def day_check(rec: Optional[dict], evs: List[dict]) -> dict:
    if not rec:
        return {"state": "none", "label": "", "verdict": "", "answers": [], "items": [], "issues": [], "summary": ""}
    if rec.get("status") == "A":
        return {"state": "absent", "label": STATE_LABELS["absent"], "verdict": "Marked absent. Nothing to pay.",
                "answers": [], "items": [], "issues": [], "summary": ""}

    photos = [e for e in evs if e.get("kind") == "photo"]
    ci_id = rec.get("check_in_photo")
    ci = next((e for e in photos if e["evidence_id"] == ci_id), None)
    work = [e for e in photos if e["evidence_id"] != ci_id and e.get("purpose") != "check_in"]
    location = rec.get("check_in_location")

    items: List[dict] = []
    pending = unavailable = False

    def add(label: str, ok: bool, detail: str = "", source: str = "check"):
        items.append({"label": label, "ok": bool(ok), "detail": detail, "source": source})

    add("Location shared", bool(location),
        f"{location['lat']:.5f}, {location['lon']:.5f}" if location else "")
    add("Check-in photo", bool(ci))

    if ci:
        ai = ci.get("ai")
        if ai is None or (ai.get("ok") and "work_status" not in ai):
            pending = True  # not read yet, or read before the current checks: needs a re-check
        elif not ai.get("ok"):
            unavailable = True
        else:
            add("Worker visible in check-in photo", ai.get("person_visible"), source="ai")
            add("Check-in photo taken on a work site", ai.get("on_site") and ai.get("is_work_related"),
                ai.get("summary", ""), source="ai")
            if ai.get("visible_timestamp"):
                add("Photo date stamp matches the day", ai.get("timestamp_date") == rec["date"],
                    ai["visible_timestamp"], source="ai")
            arrived = ai.get("timestamp_time")
            if arrived:
                add(f"On time (before {LATE_AFTER})", arrived <= LATE_AFTER, f"photo stamped {arrived}", source="ai")

    add("Work photo sent", bool(work), f"{len(work)} photo(s)" if work else "")
    latest = work[-1] if work else None
    if latest:
        ai = latest.get("ai")
        if ai is None or (ai.get("ok") and "work_status" not in ai):
            pending = True
        elif not ai.get("ok"):
            unavailable = True
        else:
            add("Work visible in work photo", ai.get("is_work_related") and ai.get("on_site")
                and ai.get("work_status") != "not_visible", ai.get("progress", ""), source="ai")
            add("Work completed", ai.get("work_status") == "completed", source="ai")

    reused = [e for e in photos if "duplicate_other_day" in (e.get("flags") or [])]
    if photos:
        add("Fresh photos (not reused from another day)", not reused,
            f"{len(reused)} reused" if reused else "")

    issues = [i["label"] for i in items if not i["ok"]]
    if not location and not ci:
        state = "manual" if rec.get("source") == "dashboard" else "no_proof"
    elif issues:
        state = "issues"
    elif pending:
        state = "pending"
    elif unavailable:
        state = "unavailable"
    else:
        state = "verified"

    attendance_finding = work_finding = ""
    if ci and (ci.get("ai") or {}).get("ok"):
        attendance_finding = ci["ai"].get("finding") or ci["ai"].get("summary", "")
    if latest and (latest.get("ai") or {}).get("ok"):
        work_finding = latest["ai"].get("finding") or latest["ai"].get("summary", "")
    work_status = ((latest or {}).get("ai") or {}).get("work_status", "") if latest else ""

    # The three answers the supervisor needs, in plain words.
    def ok(label):
        return next((i["ok"] for i in items if i["label"] == label), None)

    present_ok = bool(location) and bool(ci) and ok("Worker visible in check-in photo") is not False \
        and ok("Check-in photo taken on a work site") is not False \
        and ok("Photo date stamp matches the day") is not False
    late = ok(f"On time (before {LATE_AFTER})") is False
    genuine_ok = ok("Fresh photos (not reused from another day)") is not False
    work_ok = bool(work) and ok("Work visible in work photo") is not False and ok("Work completed") is not False
    arrived = ((ci or {}).get("ai") or {}).get("timestamp_time")

    answers = [
        {"q": "Present on site?", "ok": present_ok and not late,
         "a": (f"Present, but LATE: check-in photo stamped {arrived} (start {LATE_AFTER})." if present_ok and late else
               (attendance_finding or "Location and check-in photo received.") if present_ok else
               ("No location shared." if not location else "No check-in photo." if not ci else
                attendance_finding or "Check-in photo doesn't prove attendance."))},
        {"q": "Photos genuine?", "ok": genuine_ok,
         "a": "Real phone photos, taken for this day." if genuine_ok else
              "Photo was reused from another day."},
        {"q": "Work done?", "ok": work_ok,
         "a": (work_finding or "Work photo received.") if work_ok else
              ("No work photo sent." if not work else
               f"NOT completed: {work_finding}" if work_finding else "No work visible in the photo.")},
    ]
    if state == "verified":
        verdict = "AI confirms: present on site, photos genuine, work done. Safe to approve."
    elif state == "issues":
        verdict = "AI flags this day: " + "; ".join(a["a"] for a in answers if not a["ok"]) + " Check before approving."
    elif state == "no_proof":
        verdict = "No WhatsApp check-in for this day: no location and no photo. Don't pay without asking the worker."
    elif state == "pending":
        verdict = "AI is still reading the photos."
    elif state == "unavailable":
        verdict = "AI couldn't read the photos. Check them yourself."
    else:
        verdict = "Logged by you on the dashboard; no WhatsApp proof to check."

    return {
        "state": state,
        "label": STATE_LABELS[state],
        "verdict": verdict,
        "answers": answers if (location or ci) else [],
        "items": items,
        "issues": issues,
        "summary": " · ".join(f for f in (attendance_finding, work_finding) if f),
        "attendance": attendance_finding,
        "work": work_finding,
        "work_status": work_status,
        "sample_data": any((e.get("ai") or {}).get("demo") for e in photos),
    }


def checks_for(supervisor_id: str, site_id: str, days: List[str]) -> Dict[Tuple[str, str], dict]:
    """{(worker_id, date): check} for every register day of a site."""
    by_day: Dict[Tuple[str, str], List[dict]] = {}
    for ev in evidence.for_days(supervisor_id, site_id, days):
        by_day.setdefault((ev["worker_id"], ev["date"]), []).append(ev)
    return {
        (rec["worker_id"], rec["date"]): day_check(rec, by_day.get((rec["worker_id"], rec["date"]), []))
        for rec in attendance.days_for_site(supervisor_id, site_id, days)
    }


def counts(states: List[str]) -> Dict[str, int]:
    return dict(Counter(s for s in states if s not in ("none",)))


def snapshot_on_accept(worker_id: str, day: str) -> Optional[dict]:
    """Save what the AI check said at the moment the supervisor accepted the
    day, so the pay record shows whether it was accepted with issues."""
    from accounts import now
    from db import get_db
    rec = attendance.get_day(worker_id, day)
    if not rec:
        return None
    check = day_check(rec, evidence.for_worker_day(worker_id, day))
    snap = {"state": check["state"], "issues": check["issues"], "at": now()}
    get_db().attendance.update_one({"worker_id": worker_id, "date": day}, {"$set": {"accepted_check": snap}})
    return snap


def worker_period(day_checks: List[dict]) -> dict:
    """Roll up a worker's days for the pay screen."""
    c = counts([d["state"] for d in day_checks])
    flagged = [d for d in day_checks if d["state"] in ("issues", "no_proof")]
    return {
        "counts": c,
        "verified": c.get("verified", 0),
        "flagged": len(flagged),
        "flagged_days": [{"date": d["date"], "state": d["state"], "issues": d["issues"]} for d in flagged],
    }
