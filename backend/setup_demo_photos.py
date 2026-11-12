"""
Set up the demo account (demo@sitepay.app) with the REAL photos only.

    cd /var/www/html/sitepay/backend
    sudo docker compose exec sitepay python setup_demo_photos.py

Needs these four files in /var/www/html/sitepay/demo_assets/ :
    checkin_selfie.jpg   Musa's selfie, stamped 07:14 AM (on time)
    work_wall.jpg        Musa's finished wall
    late_selfie.jpg      selfie stamped 12 PM (late)
    unfinished_wall.jpg  wall with gaps (work not completed)

Result (each day matches the date printed on its selfie):
    11 Nov  Musa     on time + work completed      -> AI verified (waiting for you to approve)
    11 Nov  Fatima   on time + unfinished wall     -> AI flags: work not completed
    12 Nov  Chinedu  LATE selfie + finished wall   -> AI flags: late
    12 Nov  Ibrahim  absent

It also:
  - deletes every generated (drawn) image on the account
  - cancels any pay run on the account that has NOT been paid, so those days
    can be approved and paid again on camera (paid runs are never touched)

Safe to run again: it rebuilds those days for these four workers each time.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accounts  # noqa: E402
import attendance  # noqa: E402
import bot  # noqa: E402
import checks  # noqa: E402
import evidence  # noqa: E402
from db import get_db  # noqa: E402

EMAIL = "demo@sitepay.app"
ASSETS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo_assets"))
FILES = ("checkin_selfie.jpg", "work_wall.jpg", "late_selfie.jpg", "unfinished_wall.jpg")
LOCATION = {"lat": 6.55751, "lon": 3.48766}

# worker first name -> (day, check-in photo, work photo). Each day matches the
# date printed on its selfie, so the AI's date check passes.
PLAN = {
    "Musa": ("2026-11-11", "checkin_selfie.jpg", "work_wall.jpg"),
    "Fatima": ("2026-11-11", "checkin_selfie.jpg", "unfinished_wall.jpg"),
    "Chinedu": ("2026-11-12", "late_selfie.jpg", "work_wall.jpg"),
}
IBRAHIM_ABSENT = "2026-11-12"


def photo(name: str) -> bytes:
    with open(os.path.join(ASSETS, name), "rb") as f:
        return f.read()


def main():
    missing = [f for f in FILES if not os.path.exists(os.path.join(ASSETS, f))]
    if missing:
        sys.exit(f"Copy these into {ASSETS} first: {', '.join(missing)}")

    db = get_db()
    sup = db.supervisors.find_one({"email": EMAIL})
    if not sup:
        sys.exit(f"No account {EMAIL}")
    sid = sup["supervisor_id"]
    workers = {w["name"].split()[0]: w for w in accounts.list_workers(sid)}

    # 1. Generated images
    n = db.evidence.delete_many({"supervisor_id": sid, "source": "demo"}).deleted_count
    print(f"Removed {n} generated images")

    # 2. Unpaid pay runs
    for run in list(db.pay_runs.find({"supervisor_id": sid})):
        lines = list(db.pay_lines.find({"run_id": run["run_id"]}))
        if any(l["transaction_status"] not in ("NOT_SENT", "NOTHING_DUE") for l in lines):
            print(f"Kept {run['run_id']} (money was sent)")
            continue
        db.attendance.update_many({"pay_run_id": run["run_id"]}, {"$set": {"pay_run_id": None}})
        db.pay_lines.delete_many({"run_id": run["run_id"]})
        db.pay_runs.delete_one({"_id": run["_id"]})
        print(f"Cancelled unpaid run {run['run_id']}")

    # 3. Demo days, rebuilt for the four workers
    for name in ("Musa", "Chinedu", "Fatima", "Ibrahim"):
        w = workers.get(name)
        if not w:
            continue
        today = PLAN[name][0] if name in PLAN else IBRAHIM_ABSENT
        old = db.attendance.find_one({"worker_id": w["worker_id"], "date": today})
        if old and old.get("pay_run_id"):
            print(f"{name}: today is in a paid run, left alone")
            continue
        db.attendance.delete_many({"worker_id": w["worker_id"], "date": today})
        db.evidence.delete_many({"worker_id": w["worker_id"], "date": today})
        db.chat_state.update_one({"phone": w["phone"]}, {"$unset": {"check_in": ""}})

        if name == "Ibrahim":
            attendance.supervisor_set_day(sid, w["worker_id"], today,
                                          {"status": "A", "review": "accepted", "notes": "Did not check in"})
            continue
        _, ci_file, wk_file = PLAN[name]
        ci = evidence.add_photo(w, today, photo(ci_file), "", source="whatsapp")
        evidence.set_purpose(ci["evidence_id"], "check_in")
        wk = evidence.add_photo(w, today, photo(wk_file), "", source="whatsapp")
        # Same file used for two workers would be flagged as a repeat; it's
        # the same demo photo on purpose, so clear that flag.
        for ev_id in (ci["evidence_id"], wk["evidence_id"]):
            db.evidence.update_one({"evidence_id": ev_id},
                                   {"$pull": {"flags": {"$in": ["duplicate_other_day", "duplicate_same_day"]}},
                                    "$set": {"duplicate_of": None}})
        attendance.worker_check_in(w, today, LOCATION, ci["evidence_id"])

    # 4. AI reads every photo
    async def read_all():
        for name, (today, _, _) in PLAN.items():
            w = workers.get(name)
            if not w:
                continue
            rec = attendance.get_day(w["worker_id"], today)
            for ev in evidence.for_worker_day(w["worker_id"], today):
                if ev["kind"] != "photo":
                    continue
                purpose = "check_in" if ev["evidence_id"] == (rec or {}).get("check_in_photo") else "work"
                evidence.set_purpose(ev["evidence_id"], purpose)
                await bot.summarise(ev["evidence_id"], "", w.get("trade", ""), purpose, today)
    asyncio.run(read_all())

    for name, (day, _, _) in PLAN.items():
        w = workers.get(name)
        c = checks.day_check(attendance.get_day(w["worker_id"], day), evidence.for_worker_day(w["worker_id"], day))
        print(f"\n[{day}] {w['name']}: {c['label']}\n  {c['verdict']}")
        for a in c.get("answers", []):
            print(f"  {'OK' if a['ok'] else 'NO'}  {a['q']} {a['a']}")
    print(f"\n[{IBRAHIM_ABSENT}] Ibrahim Kabiru: Absent")


if __name__ == "__main__":
    main()
