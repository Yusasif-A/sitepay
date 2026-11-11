"""
The worker's WhatsApp bot. Text, photos, location and buttons only; no voice.

    any message from an unknown number → "ask your supervisor to add you"
    "hi"                               → menu: Check in · Work photo · My pay
    Check in (button, "in", "present") → starts check-in: asks for location + photo
    shared location                    → saved; asks for the photo if still missing
    photo                              → saved as evidence; asks for location if missing
    location AND photo both received   → checked in, marked Present
    "ot 2" / "2 hours overtime"        → OT claim (only once checked in)
    "pay"                              → last pay notes
    any other text                     → work note (only once checked in)

A worker is never marked Present without BOTH a shared location and a photo
for that day. Whichever half arrives first is kept in `chat_state` until the
other half arrives. Workers only ever *claim*; status, OT and advances that
affect pay are set by the supervisor on the dashboard.
"""

import asyncio
import logging
import re
from typing import Optional

import accounts
import ai
import attendance
import evidence
import payruns
import whatsapp
from accounts import now
from db import get_db
from payroll import STATUS_LABELS

logger = logging.getLogger(__name__)

BTN_CHECK_IN = {"id": "check_in", "title": "✅ Check in"}
BTN_PHOTO = {"id": "send_photo", "title": "📸 Work photo"}
BTN_PAY = {"id": "my_pay", "title": "💰 My pay"}
MENU = [BTN_CHECK_IN, BTN_PHOTO, BTN_PAY]

_CHECK_IN_WORDS = {"in", "check in", "checkin", "present", "here", "i'm here", "im here", "on site", "1"}
_PAY_WORDS = {"pay", "my pay", "payment", "money", "3"}
_MENU_WORDS = {"hi", "hello", "hey", "menu", "start", "help", "good morning", "morning"}
_OT_RE = re.compile(r"\b(?:ot|overtime|extra)\b\D{0,12}(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:h|hrs?|hours?)\s*(?:ot|overtime|extra)",
                    re.IGNORECASE)

ASK_LOCATION = ("📍 *Share your location*\n"
                "Tap 📎 (or ➕) → *Location* → *Send your current location*.")
ASK_PHOTO = ("📸 *Send a photo from the site*\n"
             "Take a photo of you at work or of the work area, and send it here.")


def _ai_tasks() -> set:
    # Keep strong references so background AI tasks aren't garbage-collected.
    if not hasattr(_ai_tasks, "s"):
        _ai_tasks.s = set()
    return _ai_tasks.s


async def handle(phone: str, reply: whatsapp.Replier, *, text: str = "", button_id: str = "",
                 image_bytes: Optional[bytes] = None, location: Optional[dict] = None,
                 wait_for_ai: bool = False) -> None:
    worker = accounts.find_worker_by_phone(phone)
    if not worker:
        await reply.text("👋 This is *SitePay*, the site pay register.\n\n"
                         "Your number isn't on a site crew yet. Ask your supervisor to add "
                         "this WhatsApp number on their SitePay dashboard, then message again.")
        return

    first = worker["name"].split()[0]
    today = attendance.today()
    lowered = (text or "").strip().lower()

    if image_bytes is not None:
        await _photo(worker, today, image_bytes, text, reply, wait_for_ai)
        return

    if location:
        await _location(worker, today, location, reply)
        return

    if button_id == BTN_CHECK_IN["id"] or lowered in _CHECK_IN_WORDS:
        await _start_check_in(worker, today, reply)
        return

    if button_id == BTN_PHOTO["id"]:
        if attendance.is_checked_in(worker["worker_id"], today):
            await reply.text("📸 Take a clear photo of the work you did (the wall, the bags loaded, the "
                             "painted room…) and send it here. Add a short caption if you like, e.g. "
                             "_Finished wall section B_.")
        else:
            await _ask_for_missing(worker, today, reply, intro="First, let's check you in for today.")
        return

    if button_id == BTN_PAY["id"] or lowered in _PAY_WORDS:
        await _my_pay(worker, reply)
        return

    if not lowered or lowered in _MENU_WORDS:
        day = attendance.get_day(worker["worker_id"], today)
        status = f"Today you're marked *{STATUS_LABELS[day['status']]}*." if day else "You haven't checked in today."
        await reply.buttons(f"👋 Hello {first}! {status}\n\nWhat would you like to do?", MENU)
        return

    if not attendance.is_checked_in(worker["worker_id"], today):
        await _ask_for_missing(worker, today, reply, intro="You haven't checked in today.")
        return

    ot = _OT_RE.search(text)
    if ot:
        hours = float(ot.group(1) or ot.group(2))
        attendance.worker_claim_ot(worker, hours, today)
        evidence.add_note(worker, today, text)
        await reply.text(f"⏱️ Noted: you're claiming *{hours:g}h overtime* today. Your supervisor "
                         "will confirm it. A photo of the extra work helps.")
        return

    evidence.add_note(worker, today, text)
    await reply.text("📝 Saved as today's work note for your supervisor. Send a photo too if you can.")


# ── Check-in: needs BOTH a location and a photo ──────────────────────────────

def _pending(worker: dict, today: str) -> dict:
    """Today's half-finished check-in: {date, location, photo_evidence_id}."""
    doc = get_db().chat_state.find_one({"phone": worker["phone"]}) or {}
    pending = doc.get("check_in") or {}
    return pending if pending.get("date") == today else {}


def _save_pending(worker: dict, today: str, **fields) -> dict:
    pending = {**_pending(worker, today), **fields, "date": today}
    get_db().chat_state.update_one(
        {"phone": worker["phone"]}, {"$set": {"check_in": pending, "updated_at": now()}}, upsert=True,
    )
    return pending


def _clear_pending(worker: dict) -> None:
    get_db().chat_state.update_one({"phone": worker["phone"]}, {"$unset": {"check_in": ""}})


async def _ask_for_missing(worker: dict, today: str, reply: whatsapp.Replier, intro: str = "") -> None:
    pending = _pending(worker, today)
    lines = [intro] if intro else []
    lines.append("To check in I need your *location* and a *photo* from the site.")
    if pending.get("location"):
        lines += ["✅ Location received.", "", ASK_PHOTO]
    elif pending.get("photo_evidence_id"):
        lines += ["✅ Photo received.", "", ASK_LOCATION]
    else:
        lines += ["", "1️⃣ " + ASK_LOCATION, "", "2️⃣ " + ASK_PHOTO]
    await reply.text("\n".join(lines))


async def _start_check_in(worker: dict, today: str, reply: whatsapp.Replier) -> None:
    first = worker["name"].split()[0]
    day = attendance.get_day(worker["worker_id"], today)
    if day:
        await reply.buttons(f"✅ You're already on today's register as *{STATUS_LABELS[day['status']]}*, "
                            f"{first}.\n\nYou can still send work photos during the day.", [BTN_PHOTO, BTN_PAY])
        return
    await _ask_for_missing(worker, today, reply, intro=f"👷 OK {first}, let's check you in.")


async def _complete_if_ready(worker: dict, today: str, reply: whatsapp.Replier) -> bool:
    pending = _pending(worker, today)
    if not (pending.get("location") and pending.get("photo_evidence_id")):
        return False
    attendance.worker_check_in(worker, today, pending["location"], pending["photo_evidence_id"])
    _clear_pending(worker)
    first = worker["name"].split()[0]
    await reply.buttons(f"✅ *Checked in*, {first}. Location and photo received. You're marked "
                        "*Present* for today.\n\nSend more work photos during or after the job.",
                        [BTN_PHOTO, BTN_PAY])
    return True


async def _location(worker: dict, today: str, location: dict, reply: whatsapp.Replier) -> None:
    if attendance.is_checked_in(worker["worker_id"], today):
        attendance.worker_check_in(worker, today, location)  # only updates the location
        await reply.text("📍 Location updated for today.")
        return
    _save_pending(worker, today, location=location)
    if not await _complete_if_ready(worker, today, reply):
        await reply.text("📍 Location received.\n\n" + ASK_PHOTO)


async def _photo(worker: dict, today: str, image_bytes: bytes, caption: str,
                 reply: whatsapp.Replier, wait_for_ai: bool) -> None:
    try:
        ev = evidence.add_photo(worker, today, image_bytes, caption or "")
    except evidence.ImageError as e:
        logger.warning(f"Photo from {worker['phone']} unreadable: {e}")
        await reply.text("I couldn't open that photo. Please send it again.")
        return
    whatsapp.log_inbound(worker["phone"], f"[photo] {caption}".strip(), ev["evidence_id"])

    warnings = []
    if "too_dark" in ev["flags"]:
        warnings.append("💡 It looks quite dark. If you can, send another one in better light.")
    if "duplicate_other_day" in ev["flags"]:
        warnings.append("⚠️ This looks like a photo sent on another day. Please send a fresh photo of today's work.")
    elif "duplicate_same_day" in ev["flags"]:
        warnings.append("ℹ️ This looks the same as a photo you already sent today.")

    checked_in = attendance.is_checked_in(worker["worker_id"], today)
    purpose = "work" if checked_in else "check_in"
    if checked_in:
        count = len([e for e in evidence.for_worker_day(worker["worker_id"], today) if e["kind"] == "photo"])
        await reply.text("\n".join([f"📸 Photo received ({count} today). Your supervisor will see it "
                                    "with today's register."] + warnings))
    else:
        evidence.set_purpose(ev["evidence_id"], "check_in")
        _save_pending(worker, today, photo_evidence_id=ev["evidence_id"])
        if warnings:
            await reply.text("\n".join(warnings))
        if not await _complete_if_ready(worker, today, reply):
            await reply.text("📸 Photo received.\n\n" + ASK_LOCATION)

    task = asyncio.create_task(summarise(ev["evidence_id"], caption or "", worker.get("trade", ""),
                                         purpose, today))
    if wait_for_ai:
        await task
    else:
        _ai_tasks().add(task)
        task.add_done_callback(_ai_tasks().discard)


async def summarise(evidence_id: str, caption: str, trade: str, purpose: str = "work",
                    expected_date: str = "") -> dict:
    jpeg = evidence.get_photo_bytes(evidence_id)
    if not jpeg:
        return {}
    result = await ai.summarise_photo(jpeg, caption, trade, purpose, expected_date)
    evidence.set_ai(evidence_id, result)
    return result


async def _my_pay(worker: dict, reply: whatsapp.Replier) -> None:
    history = payruns.runs_for_worker(worker["worker_id"])
    if not history:
        await reply.text("💰 No pay runs yet. When your supervisor approves and pays, your pay note "
                         "will arrive here.")
        return
    out = ["💰 *Your recent pay*", ""]
    for item in history:
        run, line = item["run"], item["line"]
        state = {"SUCCESS": "✅ paid", "PENDING": "⏳ sending", "UNCLAIMED": "📩 sent, claim in PayPal",
                 "NOT_SENT": "🕐 approved, not sent yet", "NOTHING_DUE": "no balance"}.get(
            line["transaction_status"], line["transaction_status"].lower())
        out.append(f"• {run['site_name']} {run['label']}: *{payruns.money(line['net'])}* ({state})")
    await reply.text("\n".join(out))
