"""
One-off: set up the demo account with the REAL photos only.

    cd /var/www/html/sitepay/backend
    sudo docker compose exec sitepay python setup_demo_photos.py

What it does (demo account demo@sitepay.app only):
  1. Removes the drawn sample images from "Load demo crew". Real WhatsApp
     photos are kept.
  2. Musa (your WhatsApp number): his real 11 Nov check-in is re-read by the
     AI and set to wait for your approval.
  3. Chinedu, today: checked in with the late selfie (stamped 12 PM) and the
     unfinished wall. The AI flags him: late, work not completed.
  4. Fatima, today: her drawn photos are gone, so her today entry is removed.
     Ibrahim stays absent.

The photos must be in demo_assets/ next to backend/ (copy them to the server:
late_selfie.jpg, unfinished_wall.jpg). Safe to run twice.
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
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo_assets")
MUSA_DAY = "2026-11-11"


def main():
    db = get_db()
    sup = db.supervisors.find_one({"email": EMAIL})
    if not sup:
        sys.exit(f"No account {EMAIL}")
    sid = sup["supervisor_id"]
    workers = {w["name"].split()[0]: w for w in accounts.list_workers(sid)}
    today = attendance.today()

    removed = db.evidence.delete_many({"supervisor_id": sid, "source": "demo"}).deleted_count
    print(f"1. Removed {removed} drawn sample images")

    musa = workers["Musa"]
    db.attendance.update_one({"worker_id": musa["worker_id"], "date": MUSA_DAY, "pay_run_id": None},
                             {"$set": {"review": "pending"}})

    ch = workers["Chinedu"]
    late = os.path.join(ASSETS, "late_selfie.jpg")
    wall = os.path.join(ASSETS, "unfinished_wall.jpg")
    if not (os.path.exists(late) and os.path.exists(wall)):
        sys.exit(f"Copy late_selfie.jpg and unfinished_wall.jpg into {os.path.abspath(ASSETS)} first")
    already = [e for e in evidence.for_worker_day(ch["worker_id"], today)
               if e["kind"] == "photo" and e.get("source") == "whatsapp"]
    if not already:
        rec = attendance.get_day(ch["worker_id"], today)
        if rec and not rec.get("pay_run_id"):
            db.attendance.delete_one({"_id": db.attendance.find_one({"worker_id": ch["worker_id"], "date": today})["_id"]})
        ci = evidence.add_photo(ch, today, open(late, "rb").read(), "", source="whatsapp")
        evidence.set_purpose(ci["evidence_id"], "check_in")
        evidence.add_photo(ch, today, open(wall, "rb").read(), "", source="whatsapp")
        attendance.worker_check_in(ch, today, {"lat": 6.55712, "lon": 3.48801}, ci["evidence_id"])
    print(f"3. Chinedu {today}: late selfie + unfinished wall attached")

    fa = workers.get("Fatima")
    if fa:
        has_photos = any(e["kind"] == "photo" for e in evidence.for_worker_day(fa["worker_id"], today))
        if not has_photos:
            db.attendance.delete_one({"worker_id": fa["worker_id"], "date": today, "pay_run_id": None})

    async def read_all():
        for w, day in ((musa, MUSA_DAY), (ch, today)):
            rec = attendance.get_day(w["worker_id"], day)
            for ev in evidence.for_worker_day(w["worker_id"], day):
                if ev["kind"] != "photo":
                    continue
                purpose = "check_in" if ev["evidence_id"] == (rec or {}).get("check_in_photo") else "work"
                evidence.set_purpose(ev["evidence_id"], purpose)
                await bot.summarise(ev["evidence_id"], ev.get("text", ""), w.get("trade", ""), purpose, day)
    asyncio.run(read_all())

    for w, day in ((musa, MUSA_DAY), (ch, today)):
        c = checks.day_check(attendance.get_day(w["worker_id"], day), evidence.for_worker_day(w["worker_id"], day))
        print(f"\n{w['name']} {day}: {c['label']}\n  {c['verdict']}")
        for a in c.get("answers", []):
            print(f"  {'OK ' if a['ok'] else 'NO '} {a['q']} {a['a']}")


if __name__ == "__main__":
    main()
