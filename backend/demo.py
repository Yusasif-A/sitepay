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
            if status != "A":
                ev = evidence.add_photo(worker, day, _sample_photo(offset * 10 + len(worker["name"]), worker["trade"]),
                                        "", source="demo")
                evidence.set_ai(ev["evidence_id"], {
                    "ok": True, "scene_type": {"Mason": "blockwork", "Painter": "painting",
                                               "Electrician": "electrical"}.get(worker["trade"], "other"),
                    "is_work_related": True, "progress": "work in progress visible",
                    "summary": f"{worker['trade']} work visible on site; looks consistent with the day's task.",
                    "image_quality": "good", "confidence": "medium", "flags": [], "demo": True,
                })
    return {"site": site, "workers": workers,
            "using_placeholder_emails": not receivers}


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
