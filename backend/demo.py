"""
Demo data: one site with the four workers from the product doc and the past
six days of register. Today is left empty, so the live demo starts with a
worker checking in.

    POST /api/demo/seed    (dashboard button "Load demo crew")
    python demo.py you@example.com   (CLI, for an existing supervisor)

Workers get PayPal *sandbox* personal-account emails from
DEMO_PAYPAL_RECEIVERS (comma-separated) if set; otherwise placeholders you
should replace with your sandbox personal account (Developer Dashboard →
Testing Tools → Sandbox Accounts).
"""

import io
import os
import random
import sys
from datetime import date, timedelta

import accounts
import attendance
import evidence
from db import get_db

CREW = [
    # name, trade, daily rate, phone suffix
    ("Musa Abdullahi", "Mason", 12000, "01"),
    ("Chinedu Okafor", "Labourer", 6500, "02"),
    ("Fatima Bello", "Painter", 9000, "03"),
    ("Ibrahim Kabiru", "Electrician", 15000, "04"),
]

# day offset (1 = yesterday) → per-worker (status, ot_hours, advance, note)
PATTERN = {
    1: [("OT", 2, 0, ""), ("H", 0, 1000, "Left 1pm"), ("P", 0, 0, ""), ("A", 0, 0, "")],
    2: [("P", 0, 0, ""), ("P", 0, 0, ""), ("P", 0, 0, ""), ("P", 0, 0, "")],
    3: [("P", 0, 2000, "Advance for transport"), ("P", 0, 0, ""), ("H", 0, 0, "Rain stopped work"), ("P", 1, 0, "")],
    4: [("P", 0, 0, ""), ("A", 0, 0, ""), ("P", 0, 0, ""), ("P", 0, 0, "")],
    5: [("P", 0, 0, ""), ("P", 0, 0, ""), ("P", 0, 0, ""), ("OT", 3, 0, "Finished wiring floor 2")],
    6: [("P", 0, 0, ""), ("P", 0, 500, ""), ("A", 0, 0, ""), ("P", 0, 0, "")],
}


def _sample_photo(seed: int, kind: str) -> bytes:
    """A simple drawn 'site photo' (brick wall / painted wall / cable runs),
    distinct per day so the duplicate check doesn't fire on seed data."""
    from PIL import Image, ImageDraw
    rnd = random.Random(seed)
    img = Image.new("RGB", (800, 600), (150 + rnd.randint(0, 40), 180, 205))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 430, 800, 600], fill=(120 + rnd.randint(0, 30), 100, 70))
    if kind == "Mason":
        rows = rnd.randint(6, 11)
        for r in range(rows):
            y = 430 - (r + 1) * 30
            off = 0 if r % 2 else 40
            for x in range(-40 + off, 760, 80):
                shade = rnd.randint(-15, 15)
                d.rectangle([x + 60, y, x + 136, y + 26], fill=(175 + shade, 75 + shade, 55), outline=(200, 200, 190))
    elif kind == "selfie":
        # A figure in hard hat + hi-vis in front of a block frame.
        d.rectangle([420, 120, 760, 430], fill=(185, 182, 172))
        for y in range(140, 430, 40):
            d.line([420, y, 760, y], fill=(150, 148, 140), width=3)
        cx = 260 + rnd.randint(-30, 30)
        d.ellipse([cx - 50, 170, cx + 50, 270], fill=(110, 70, 45))
        d.pieslice([cx - 58, 140, cx + 58, 230], 180, 360, fill=(250, 200, 20))
        d.rounded_rectangle([cx - 90, 270, cx + 90, 600], 30, fill=(200, 230, 40))
    elif kind == "Painter":
        split = rnd.randint(250, 600)
        d.rectangle([60, 60, split, 430], fill=(235, 230, 210))
        d.rectangle([split, 60, 740, 430], fill=(160, 155, 145))
        d.rectangle([split - 10, 300, split + 40, 330], fill=(90, 60, 40))
    else:
        d.rectangle([60, 60, 740, 430], fill=(200, 200, 195))
        for i in range(rnd.randint(3, 6)):
            y = 100 + i * 50
            d.line([80, y, 720, y + rnd.randint(-20, 20)], fill=(rnd.randint(0, 200), 20, 20), width=5)
        d.rectangle([600, 120, 690, 230], fill=(70, 70, 75))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def seed_for(supervisor_id: str) -> dict:
    receivers = [r.strip() for r in os.getenv("DEMO_PAYPAL_RECEIVERS", "").split(",") if r.strip()]
    site = accounts.create_site(supervisor_id, "Lekki Phase 2 Duplex", "Lekki, Lagos")
    prefix = "23480" + str(random.randint(10000, 99999))
    workers = []
    for i, (name, trade, rate, suffix) in enumerate(CREW):
        email = receivers[i % len(receivers)] if receivers else f"{name.split()[0].lower()}.demo@personal.example.com"
        workers.append(accounts.create_worker(
            supervisor_id, name=name, trade=trade, daily_rate=rate, phone=prefix + suffix,
            site_id=site["site_id"], paypal_email=email,
        ))

    today = date.fromisoformat(attendance.today())
    for offset, plan in PATTERN.items():
        day = (today - timedelta(days=offset)).isoformat()
        for worker, (status, ot, adv, note) in zip(workers, plan):
            attendance.supervisor_set_day(supervisor_id, worker["worker_id"], day, {
                "status": status, "ot_hours": ot, "advance": adv, "notes": note, "review": "accepted",
            })
            # No generated photos: past days are logged by the supervisor.
            # Real photos come only from WhatsApp.
            continue
            if status != "A":
                trade = worker["trade"]
                scene = {"Mason": "blockwork", "Painter": "painting", "Electrician": "electrical"}.get(trade, "other")
                work_line = {
                    "Mason": "Blockwork in progress: new wall courses laid with mortar joints.",
                    "Painter": "Painting in progress: wall section has a fresh coat; rest still bare.",
                    "Electrician": "Electrical work in progress: cable runs fixed along the wall.",
                }.get(trade, "Labour on site: materials moved and stacked at the work area.")
                ci = evidence.add_photo(worker, day, _sample_photo(offset * 10 + len(worker["name"]) + 500, "selfie"),
                                        "", source="demo")
                evidence.set_purpose(ci["evidence_id"], "check_in")
                evidence.set_ai(ci["evidence_id"], {
                    "ok": True, "purpose": "check_in", "scene_type": scene, "is_work_related": True,
                    "person_visible": True, "on_site": True, "work_status": "not_visible",
                    "finding": f"Worker present on site: {trade.lower()} in PPE at the Lekki duplex site.",
                    "summary": f"{trade} on site at the start of the day.", "progress": "",
                    "visible_timestamp": "", "timestamp_date": None,
                    "image_quality": "good", "confidence": "medium", "flags": [], "demo": True,
                })
                wk = evidence.add_photo(worker, day, _sample_photo(offset * 10 + len(worker["name"]), trade),
                                        "", source="demo")
                evidence.set_ai(wk["evidence_id"], {
                    "ok": True, "purpose": "work", "scene_type": scene, "is_work_related": True,
                    "person_visible": False, "on_site": True, "work_status": "in_progress",
                    "finding": work_line, "summary": work_line, "progress": "work in progress",
                    "visible_timestamp": "", "timestamp_date": None,
                    "image_quality": "good", "confidence": "medium", "flags": [], "demo": True,
                })
                get_db().attendance.update_one(
                    {"worker_id": worker["worker_id"], "date": day},
                    {"$set": {"check_in_location": {"lat": 6.4474 + offset * 0.0001, "lon": 3.4723},
                              "check_in_photo": ci["evidence_id"], "check_in_at": accounts.now()}},
                )
    return {"site": site, "workers": workers,
            "using_placeholder_emails": not receivers}


def add_today_examples(supervisor_id: str, site_id: str) -> dict:
    """Today's register for the other crew, to show the AI working both ways:

        Chinedu   checked in, AI verifies him (good)
        Fatima    checked in, AI flags her (reused photo, no work visible)
        Ibrahim   absent

    Musa (the worker demoing on WhatsApp) is left alone. Days that already
    exist are never overwritten."""
    today = attendance.today()
    workers = {w["name"].split()[0]: w for w in accounts.list_workers(supervisor_id, site_id, active_only=True)}
    done = []

    def free(name):
        w = workers.get(name)
        return w if w and not attendance.get_day(w["worker_id"], today) else None

    w = free("Chinedu")
    if w:
        attendance.supervisor_set_day(supervisor_id, w["worker_id"], today, {"status": "P", "review": "pending"})
        get_db().attendance.update_one({"worker_id": w["worker_id"], "date": today}, {"$set": {"source": "whatsapp"}})
        _demo_checkin(w, today, 21, good=True)
        done.append("Chinedu: AI verified")

    w = free("Fatima")
    if w:
        attendance.supervisor_set_day(supervisor_id, w["worker_id"], today, {"status": "P", "review": "pending"})
        get_db().attendance.update_one({"worker_id": w["worker_id"], "date": today}, {"$set": {"source": "whatsapp"}})
        _demo_checkin(w, today, 33, good=False)
        done.append("Fatima: AI flagged")

    w = free("Ibrahim")
    if w:
        attendance.supervisor_set_day(supervisor_id, w["worker_id"], today, {"status": "A", "review": "accepted",
                                                                             "notes": "Did not check in"})
        done.append("Ibrahim: absent")
    return {"date": today, "added": done}


def _demo_checkin(worker: dict, day: str, seed: int, good: bool) -> None:
    trade = worker["trade"]
    ci = evidence.add_photo(worker, day, _sample_photo(seed + 900, "selfie"), "", source="demo")
    evidence.set_purpose(ci["evidence_id"], "check_in")
    wk = evidence.add_photo(worker, day, _sample_photo(seed + 950, trade), "", source="demo")
    if good:
        ci_ai = {"person_visible": True, "on_site": True, "real_photo": True, "work_status": "not_visible",
                 "finding": f"Worker present on site: {trade.lower()} in hard hat and hi-vis at the Lekki duplex."}
        wk_ai = {"person_visible": False, "on_site": True, "real_photo": True, "work_status": "completed",
                 "finding": "Work completed: blocks moved and stacked at the second-floor stairwell, area cleared."}
        wk_flags = []
    else:
        ci_ai = {"person_visible": True, "on_site": True, "real_photo": True, "work_status": "not_visible",
                 "finding": "Worker visible, but the same photo was sent on an earlier day."}
        wk_ai = {"person_visible": False, "on_site": False, "real_photo": True, "work_status": "not_visible",
                 "finding": "No work visible: photo shows a plain indoor wall, not the site."}
        wk_flags = ["not_on_site"]
    for ev_id, extra, flags in ((ci["evidence_id"], ci_ai, [] if good else ["duplicate_other_day"]),
                                (wk["evidence_id"], wk_ai, wk_flags)):
        # The drawn sample photos can look alike to the duplicate check;
        # the example decides on purpose which one is "reused".
        get_db().evidence.update_one({"evidence_id": ev_id},
                                     {"$pull": {"flags": {"$in": ["duplicate_other_day", "duplicate_same_day"]}},
                                      "$set": {"duplicate_of": None}})
        evidence.set_ai(ev_id, {
            "ok": True, "is_work_related": extra["on_site"], "progress": "", "summary": extra["finding"],
            "visible_timestamp": "", "timestamp_date": None, "image_quality": "good", "confidence": "high",
            "flags": [f for f in flags if f != "duplicate_other_day"], "demo": True, **extra,
        })
        if "duplicate_other_day" in flags:
            get_db().evidence.update_one({"evidence_id": ev_id}, {"$addToSet": {"flags": "duplicate_other_day"}})
    get_db().attendance.update_one(
        {"worker_id": worker["worker_id"], "date": day},
        {"$set": {"check_in_location": {"lat": 6.4474, "lon": 3.4723}, "check_in_photo": ci["evidence_id"],
                  "check_in_at": accounts.now()}},
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python demo.py supervisor@email")
        raise SystemExit(1)
    sup = get_db().supervisors.find_one({"email": sys.argv[1].lower()})
    if not sup:
        print("No supervisor with that email. Sign up on the dashboard first.")
        raise SystemExit(1)
    result = seed_for(sup["supervisor_id"])
    print(f"Seeded site {result['site']['name']} with {len(result['workers'])} workers.")
