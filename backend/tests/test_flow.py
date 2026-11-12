"""End to end through the HTTP API, as the demo runs it:
signup → crew → worker WhatsApp (simulator) check-in + photo → register
edit → approve → PayPal payout → pay note on WhatsApp."""

import io
import json
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client():
    from app import app
    with TestClient(app) as c:
        yield c


def photo(color=(180, 90, 60), size=(640, 480), pattern=0):
    img = Image.new("RGB", size, color)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    for i in range(pattern + 1):
        d.rectangle([20 + i * 90, 40, 80 + i * 90, 400], fill=(240, 240, 240))
    buf = io.BytesIO()
    # Include EXIF to prove it's stripped
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def signup(client, email="sup@example.com"):
    r = client.post("/api/auth/signup", json={"name": "Ade Supervisor", "email": email, "password": "password123",
                                              "site_name": "Site X", "company": "Ade Builders"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    site_id = client.get("/api/me", headers=h).json()["sites"][0]["site_id"]
    return h, site_id


def add_worker(client, h, site_id, name, phone, rate, email):
    r = client.post("/api/workers", headers=h, json={"name": name, "phone": phone, "site_id": site_id,
                                                     "daily_rate": rate, "trade": "Mason", "paypal_email": email})
    assert r.status_code == 200, r.text
    return r.json()


def test_auth(client):
    h, _ = signup(client)
    assert client.post("/api/auth/signup", json={"name": "x", "email": "sup@example.com",
                                                 "password": "password123"}).status_code == 422
    assert client.post("/api/auth/login", json={"email": "sup@example.com", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "SUP@example.com", "password": "password123"}).status_code == 200
    assert client.get("/api/me").status_code == 401


def test_supervisors_are_isolated(client):
    h1, site1 = signup(client, "a@example.com")
    h2, _ = signup(client, "b@example.com")
    w = add_worker(client, h1, site1, "Musa A", "08031111111", 12000, "musa@x.com")
    assert client.get(f"/api/register?site_id={site1}&date=2025-11-09", headers=h2).status_code == 404
    assert client.put(f"/api/register/{w['worker_id']}/2025-11-09", headers=h2, json={"status": "P"}).status_code == 422
    assert client.post("/api/workers", headers=h2, json={"name": "X", "phone": "0803222", "site_id": site1,
                                                         "daily_rate": 1}).status_code == 422


def test_full_demo_flow_simulated(client):
    from db import get_db
    import attendance

    h, site = signup(client)
    musa = add_worker(client, h, site, "Musa Abdullahi", "0803 111 1111", 12000, "musa@personal.example.com")
    chinedu = add_worker(client, h, site, "Chinedu Okafor", "+234 803 222 2222", 6500, "chinedu@personal.example.com")
    assert musa["phone"] == "2348031111111"
    today = attendance.today()

    # Unknown number on the real webhook gets told to ask the supervisor
    import bot, whatsapp, asyncio
    asyncio.run(bot.handle("2349999999999", whatsapp.Replier("2349999999999", True), text="hi"))
    assert "isn't on a site crew" in whatsapp.chat_history("2349999999999")[-1]["text"]

    # Worker: hi → menu; Check in alone must NOT mark Present
    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, data={"text": "hi"})
    assert r.json()["messages"][-1]["buttons"]
    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, data={"button_id": "check_in"})
    ask = r.json()["messages"][-1]["text"]
    assert "location" in ask and "photo" in ask
    assert attendance.get_day(musa["worker_id"], today) is None
    # Notes / OT claims before check-in are refused
    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, data={"text": "2 hours overtime"})
    assert "haven't checked in" in r.json()["messages"][-1]["text"]
    assert attendance.get_day(musa["worker_id"], today) is None

    # Location only → still not Present, asks for photo
    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, data={"lat": "6.4474", "lon": "3.4723"})
    assert "Send a photo" in r.json()["messages"][-1]["text"]
    assert attendance.get_day(musa["worker_id"], today) is None

    # Photo → now checked in with both
    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, data={"text": "Finished wall section B"},
                    files={"file": ("w.jpg", photo(), "image/jpeg")})
    assert "Checked in" in r.json()["messages"][-1]["text"]
    day = attendance.get_day(musa["worker_id"], today)
    assert day["status"] == "P" and day["check_in_location"] and day["check_in_photo"]

    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, data={"text": "I did 2 hours overtime"})
    assert "2h overtime" in r.json()["messages"][-1]["text"]

    # Same photo again → duplicate flag
    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, files={"file": ("w.jpg", photo(), "image/jpeg")})
    assert "same as a photo" in r.json()["messages"][-1]["text"]

    # Other order for Chinedu: photo first, then location
    r = client.post(f"/api/simulator/{chinedu['worker_id']}", headers=h,
                    files={"file": ("c.jpg", photo((60, 120, 180), pattern=3), "image/jpeg")})
    assert "Share your location" in r.json()["messages"][-1]["text"]
    assert attendance.get_day(chinedu["worker_id"], today) is None
    r = client.post(f"/api/simulator/{chinedu['worker_id']}", headers=h, data={"lat": "6.45", "lon": "3.47"})
    assert "Checked in" in r.json()["messages"][-1]["text"]

    # Stored image has no EXIF
    ev = get_db().evidence.find_one({"worker_id": musa["worker_id"], "kind": "photo"})
    assert not Image.open(io.BytesIO(bytes(ev["image"]))).getexif()

    # Supervisor: register shows the day + evidence; worker claims don't change pay
    reg = client.get(f"/api/register?site_id={site}&date={today}", headers=h).json()
    row = next(r for r in reg["rows"] if r["worker_id"] == musa["worker_id"])
    assert row["status"] == "P" and row["ot_claim_hours"] == 2 and row["ot_hours"] == 0
    assert row["photo_count"] == 2 and "duplicate_same_day" in row["flags"]
    assert row["evidence"][0]["has_image"]
    img = client.get(f"/api/evidence/{row['evidence'][0]['evidence_id']}/image", headers=h)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"

    # Supervisor accepts OT, marks Chinedu half day with an advance
    r = client.put(f"/api/register/{musa['worker_id']}/{today}", headers=h, json={"ot_hours": 2, "review": "accepted"})
    assert r.json()["status"] == "OT"
    client.put(f"/api/register/{chinedu['worker_id']}/{today}", headers=h,
               json={"status": "H", "advance": 1000, "notes": "Left 1pm", "review": "accepted"})
    assert client.put(f"/api/register/{chinedu['worker_id']}/{today}", headers=h,
                      json={"status": "X"}).status_code == 422

    # Preview
    prev = client.get(f"/api/payruns/preview?site_id={site}&start={today}&end={today}", headers=h).json()
    assert prev["simulate"] is True
    lines = {l["worker_id"]: l for l in prev["lines"]}
    assert lines[musa["worker_id"]]["net"] == 12000 + 2 * 2250
    assert lines[chinedu["worker_id"]]["net"] == 3250 - 1000
    assert lines[chinedu["worker_id"]]["payout_amount"] == "1.50"

    # Approve → days locked
    run = client.post("/api/payruns", headers=h, json={"site_id": site, "start": today, "end": today}).json()
    assert run["status"] == "approved" and run["total_net"] == 16500 + 2250
    locked = client.put(f"/api/register/{musa['worker_id']}/{today}", headers=h, json={"status": "A"})
    assert locked.status_code == 409
    # A second approval for the same period has nothing left
    assert client.post("/api/payruns", headers=h, json={"site_id": site, "start": today, "end": today}).status_code == 422
    musa_line = next(l for l in run["lines"] if l["worker_id"] == musa["worker_id"])
    assert len(musa_line["evidence_ids"]) == 3  # 2 photos + OT text note

    # Pay (simulated PayPal) → completed + WhatsApp pay note
    paid = client.post(f"/api/payruns/{run['run_id']}/pay", headers=h).json()
    assert paid["status"] == "completed" and paid["payout_batch_id"].startswith("SIM")
    assert all(l["transaction_status"] == "SUCCESS" and l["notified"] for l in paid["lines"])
    assert client.post(f"/api/payruns/{run['run_id']}/pay", headers=h).status_code == 422  # no double pay
    msgs = client.get(f"/api/simulator/{musa['worker_id']}", headers=h).json()["messages"]
    note = msgs[-1]["text"]
    assert "you've been paid" in note
    assert "Overtime 1 day, plus 2h overtime" in note
    assert "*Net: ₦16,500*" in note
    assert "11.00 USD" in note

    # My pay on WhatsApp
    r = client.post(f"/api/simulator/{musa['worker_id']}", headers=h, data={"button_id": "my_pay"})
    assert "₦16,500" in r.json()["messages"][-1]["text"]


def test_approve_requires_paypal_email(client):
    import attendance
    h, site = signup(client)
    w = add_worker(client, h, site, "No Email", "08035555555", 5000, "")
    client.put(f"/api/register/{w['worker_id']}/{attendance.today()}", headers=h, json={"status": "P", "review": "accepted"})
    t = attendance.today()
    r = client.post("/api/payruns", headers=h, json={"site_id": site, "start": t, "end": t})
    assert r.status_code == 422 and "PayPal email" in r.json()["detail"]


def test_real_paypal_path_with_mock_transport(client, monkeypatch):
    """The non-simulated path calls the real client: verify the batch it sends
    and that statuses flow back."""
    import attendance
    import paypal

    sent = {}

    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 32400})
        if request.method == "POST" and request.url.path == "/v1/payments/payouts":
            sent["body"] = json.loads(request.content)
            return httpx.Response(201, json={"batch_header": {"payout_batch_id": "PB123", "batch_status": "PENDING"}})
        if request.url.path == "/v1/payments/payouts/PB123":
            items = [{"payout_item_id": "I1", "transaction_id": "TX1", "transaction_status": "SUCCESS",
                      "payout_item": {"sender_item_id": it["sender_item_id"]}} for it in sent["body"]["items"]]
            return httpx.Response(200, json={"batch_header": {"payout_batch_id": "PB123", "batch_status": "SUCCESS"},
                                             "items": items})
        raise AssertionError(request.url)

    paypal.set_client(paypal.PayPalClient("cid", "sec", "https://api-m.sandbox.paypal.com",
                                          transport=httpx.MockTransport(handler)))
    h, site = signup(client)
    w = add_worker(client, h, site, "Fatima Bello", "08033333333", 9000, "fatima@personal.example.com")
    t = attendance.today()
    y = (date.fromisoformat(t) - timedelta(days=1)).isoformat()
    for d in (y, t):
        client.put(f"/api/register/{w['worker_id']}/{d}", headers=h, json={"status": "P", "review": "accepted"})
    run = client.post("/api/payruns", headers=h, json={"site_id": site, "start": y, "end": t}).json()
    assert run["simulated"] is False
    paid = client.post(f"/api/payruns/{run['run_id']}/pay", headers=h).json()
    assert sent["body"]["sender_batch_header"]["sender_batch_id"] == run["run_id"] + "-1"
    assert sent["body"]["items"][0]["amount"] == {"value": "12.00", "currency": "USD"}
    assert "Site X" in sent["body"]["items"][0]["note"]
    assert paid["status"] == "completed" and paid["lines"][0]["transaction_id"] == "TX1"


def test_paypal_failure_allows_retry(client):
    import attendance
    import paypal

    state = {"fail": True}

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 32400})
        if request.method == "POST":
            if state["fail"]:
                return httpx.Response(422, json={"name": "INSUFFICIENT_FUNDS", "message": "x"})
            return httpx.Response(201, json={"batch_header": {"payout_batch_id": "PB9", "batch_status": "PENDING"}})
        return httpx.Response(200, json={"batch_header": {"batch_status": "PROCESSING"}, "items": []})

    paypal.set_client(paypal.PayPalClient("c", "s", "https://x", transport=httpx.MockTransport(handler)))
    h, site = signup(client)
    w = add_worker(client, h, site, "Ibrahim K", "08034444444", 15000, "ib@personal.example.com")
    t = attendance.today()
    client.put(f"/api/register/{w['worker_id']}/{t}", headers=h, json={"status": "P", "review": "accepted"})
    run = client.post("/api/payruns", headers=h, json={"site_id": site, "start": t, "end": t}).json()
    r = client.post(f"/api/payruns/{run['run_id']}/pay", headers=h)
    assert r.status_code == 422 and "enough balance" in r.json()["detail"]
    assert client.get(f"/api/payruns/{run['run_id']}", headers=h).json()["status"] == "failed"
    state["fail"] = False
    ok = client.post(f"/api/payruns/{run['run_id']}/pay", headers=h).json()
    assert ok["status"] == "submitted" and ok["payout_batch_id"] == "PB9"


def test_demo_seed(client):
    h, _ = signup(client)
    r = client.post("/api/demo/seed", headers=h)
    assert r.status_code == 200
    site = r.json()["site"]["site_id"]
    import attendance
    t = date.fromisoformat(attendance.today())
    start, end = (t - timedelta(days=6)).isoformat(), (t - timedelta(days=1)).isoformat()
    prev = client.get(f"/api/payruns/preview?site_id={site}&start={start}&end={end}", headers=h).json()
    assert len(prev["lines"]) == 4 and prev["total_net"] > 0


def test_webhook_verify_and_text(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "vt")
    r = client.get("/whatsapp?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=123")
    assert r.text == "123"
    assert client.get("/whatsapp?hub.verify_token=bad&hub.challenge=1").status_code == 403
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "2348000000000", "id": "m1", "type": "audio", "audio": {"id": "a"}}]}}]}]}
    assert client.post("/whatsapp", json=payload).status_code == 200


def test_schedule_sends_whatsapp_and_shows_on_calendar(client):
    import attendance
    import whatsapp
    h, site = signup(client)
    w = add_worker(client, h, site, "Musa Abdullahi", "08030000001", 12000, "musa@personal.example.com")
    t = attendance.today()
    tomorrow = (date.fromisoformat(t) + timedelta(days=1)).isoformat()
    day3 = (date.fromisoformat(t) + timedelta(days=3)).isoformat()

    r = client.post("/api/schedule", headers=h, json={"site_id": site, "worker_id": w["worker_id"],
                                                      "start": tomorrow, "end": day3, "task": "Blockwork, 2nd floor",
                                                      "start_time": "07:30"})
    assert r.status_code == 200, r.text
    assert len(r.json()["shifts"]) == 3
    msg = whatsapp.chat_history(w["phone"])[-1]["text"]
    assert "you've been scheduled" in msg and "Blockwork, 2nd floor" in msg and "07:30" in msg and "(3 days)" in msg
    assert "Check in" in msg

    cal = client.get(f"/api/register/range?site_id={site}&start={t}&end={day3}", headers=h).json()
    assert sorted(s["date"] for s in cal["shifts"]) == [tomorrow, (date.fromisoformat(t) + timedelta(days=2)).isoformat(), day3]
    assert all(s["notified"] for s in cal["shifts"])

    # Past days can't be scheduled
    yesterday = (date.fromisoformat(t) - timedelta(days=1)).isoformat()
    bad = client.post("/api/schedule", headers=h, json={"site_id": site, "worker_id": w["worker_id"],
                                                        "start": yesterday, "end": yesterday})
    assert bad.status_code == 422

    # Removing a shift tells the worker
    r = client.delete(f"/api/schedule/{w['worker_id']}/{tomorrow}", headers=h)
    assert r.status_code == 200
    assert "no longer scheduled" in whatsapp.chat_history(w["phone"])[-1]["text"]

    # Scheduling never touches pay
    assert attendance.get_day(w["worker_id"], tomorrow) is None


def test_ai_stamp_date_parsing():
    import ai
    assert ai._stamp_date("11 NOV 2026 07:14 AM") == "2026-11-11"
    assert ai._stamp_date("2026-11-11 07:14") == "2026-11-11"
    assert ai._stamp_date("11/11/2026") == "2026-11-11"
    assert ai._stamp_date("07:14 AM") is None


def test_pay_one_worker_then_the_rest(client):
    """Per-worker Pay button, then Pay all for whoever is left; nobody paid twice."""
    import attendance
    import whatsapp
    h, site = signup(client)
    a = add_worker(client, h, site, "Musa Abdullahi", "08030000001", 12000, "musa@personal.example.com")
    b = add_worker(client, h, site, "Chinedu Okafor", "08030000002", 6500, "chinedu@personal.example.com")
    c = add_worker(client, h, site, "Fatima Bello", "08030000003", 9000, "fatima@personal.example.com")
    t = attendance.today()
    for w in (a, b, c):
        client.put(f"/api/register/{w['worker_id']}/{t}", headers=h, json={"status": "P", "review": "accepted"})
    run = client.post("/api/payruns", headers=h, json={"site_id": site, "start": t, "end": t}).json()

    # Pay only Musa
    r = client.post(f"/api/payruns/{run['run_id']}/pay", headers=h, json={"worker_ids": [a["worker_id"]]}).json()
    lines = {l["worker_id"]: l for l in r["lines"]}
    assert lines[a["worker_id"]]["transaction_status"] == "SUCCESS" and lines[a["worker_id"]]["notified"]
    assert lines[b["worker_id"]]["transaction_status"] == "NOT_SENT"
    assert lines[c["worker_id"]]["transaction_status"] == "NOT_SENT"
    assert r["status"] == "partial"
    assert "you've been paid" in whatsapp.chat_history(a["phone"])[-1]["text"]
    assert not whatsapp.chat_history(b["phone"])

    # Paying Musa again is refused
    again = client.post(f"/api/payruns/{run['run_id']}/pay", headers=h, json={"worker_ids": [a["worker_id"]]})
    assert again.status_code == 422

    # Pay all → only the two still unpaid go out
    r = client.post(f"/api/payruns/{run['run_id']}/pay", headers=h).json()
    assert r["status"] == "completed"
    assert all(l["transaction_status"] == "SUCCESS" for l in r["lines"])
    assert len(r["batches"]) == 2
    assert sorted(r["batches"][1]["worker_ids"]) == sorted([b["worker_id"], c["worker_id"]])
    assert client.post(f"/api/payruns/{run['run_id']}/pay", headers=h).status_code == 422


def test_check_in_still_asks_for_proof_when_day_already_exists(client):
    """A day logged without proof (dashboard, or an old record) must still ask
    the worker for location + photo, and attach them without changing pay."""
    import attendance
    h, site = signup(client)
    w = add_worker(client, h, site, "Musa Abdullahi", "08030000001", 12000, "musa@personal.example.com")
    t = attendance.today()
    client.put(f"/api/register/{w['worker_id']}/{t}", headers=h, json={"status": "P", "review": "accepted"})

    r = client.post(f"/api/simulator/{w['worker_id']}", headers=h, data={"button_id": "check_in"})
    ask = r.json()["messages"][-1]["text"]
    assert "location" in ask and "photo" in ask
    r = client.post(f"/api/simulator/{w['worker_id']}", headers=h, data={"text": "hi"})
    assert "haven't checked in" in r.json()["messages"][-1]["text"]

    client.post(f"/api/simulator/{w['worker_id']}", headers=h, data={"lat": "6.45", "lon": "3.47"})
    r = client.post(f"/api/simulator/{w['worker_id']}", headers=h, files={"file": ("s.jpg", photo(), "image/jpeg")})
    assert "Checked in" in r.json()["messages"][-1]["text"]
    day = attendance.get_day(w["worker_id"], t)
    assert day["check_in_location"] and day["check_in_photo"] and day["status"] == "P"

    r = client.post(f"/api/simulator/{w['worker_id']}", headers=h, data={"button_id": "check_in"})
    assert "already checked in" in r.json()["messages"][-1]["text"]


def test_only_approved_days_are_paid_and_pay_now_is_one_click(client):
    import attendance
    h, site = signup(client)
    a = add_worker(client, h, site, "Musa Abdullahi", "08030000001", 12000, "musa@personal.example.com")
    b = add_worker(client, h, site, "Chinedu Okafor", "08030000002", 6500, "chinedu@personal.example.com")
    t = attendance.today()
    client.put(f"/api/register/{a['worker_id']}/{t}", headers=h, json={"status": "P"})          # not approved
    client.put(f"/api/register/{b['worker_id']}/{t}", headers=h, json={"status": "P", "review": "accepted"})

    prev = client.get(f"/api/payruns/preview?site_id={site}&start={t}&end={t}", headers=h).json()
    lines = {l["worker_id"]: l for l in prev["lines"]}
    assert lines[a["worker_id"]]["net"] == 0 and lines[a["worker_id"]]["awaiting_approval"] == 1
    assert lines[b["worker_id"]]["net"] == 6500

    # Musa can't be paid until approved
    r = client.post("/api/pay-now", headers=h, json={"site_id": site, "start": t, "end": t, "worker_ids": [a["worker_id"]]})
    assert r.status_code == 422 and "approve" in r.json()["detail"].lower()

    client.put(f"/api/register/{a['worker_id']}/{t}", headers=h, json={"review": "accepted"})
    r = client.post("/api/pay-now", headers=h, json={"site_id": site, "start": t, "end": t, "worker_ids": [a["worker_id"]]})
    assert r.status_code == 200, r.text
    run = r.json()
    assert [l["worker_id"] for l in run["lines"]] == [a["worker_id"]]
    assert run["lines"][0]["transaction_status"] == "SUCCESS" and run["lines"][0]["notified"]

    # Chinedu is still waiting; Pay all pays only him
    r = client.post("/api/pay-now", headers=h, json={"site_id": site, "start": t, "end": t}).json()
    assert [l["worker_id"] for l in r["lines"]] == [b["worker_id"]]


def test_today_examples_show_good_and_bad(client):
    import attendance
    h, _ = signup(client)
    site = client.post("/api/demo/seed", headers=h).json()["site"]["site_id"]
    r = client.post("/api/demo/today", headers=h, json={"site_id": site})
    assert r.status_code == 200, r.text
    t = attendance.today()
    rows = {x["name"].split()[0]: x for x in client.get(f"/api/register?site_id={site}&date={t}", headers=h).json()["rows"]}
    assert rows["Chinedu"]["check"]["state"] == "verified"
    assert rows["Chinedu"]["check"]["verdict"].startswith("AI confirms")
    assert rows["Fatima"]["check"]["state"] == "issues"
    assert any(not a["ok"] for a in rows["Fatima"]["check"]["answers"])
    assert rows["Ibrahim"]["status"] == "A"
    assert not rows["Musa"]["logged"]
    # Running it again doesn't overwrite anything
    again = client.post("/api/demo/today", headers=h, json={"site_id": site}).json()
    assert again["added"] == []
