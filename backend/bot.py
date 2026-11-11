"""
The worker's WhatsApp bot. Text, photos, location and buttons only; no voice.

    any message from an unknown number → "ask your supervisor to add you"
    "hi" / anything first thing        → menu: Check in · Work photo · My pay
    Check in (button, "in", "present") → today's register line, status P
    shared location                    → check in with location attached
    photo                              → check in + work evidence, AI summary
    "ot 2" / "2 hours overtime"        → OT claim (supervisor decides)
    "pay"                              → last pay notes
    any other text                     → saved as a work note for today

Workers only ever *claim*. Status, OT and advances that affect pay are set
by the supervisor on the dashboard.
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
        attendance.worker_check_in(worker, today, location)
        await reply.buttons(f"📍 Location received. You're checked in for today, {first}.\n\n"
                            "Send a photo of your work any time today.", [BTN_PHOTO, BTN_PAY])
        return

    if button_id == BTN_CHECK_IN["id"] or lowered in _CHECK_IN_WORDS:
        await _check_in(worker, today, reply)
        return

    if button_id == BTN_PHOTO["id"]:
        await reply.text("📸 Take a clear photo of the work you did (the wall, the bags loaded, the "
                         "painted room…) and send it here. Add a short caption if you like, e.g. "
                         "_Finished wall section B_.")
        return

    if button_id == BTN_PAY["id"] or lowered in _PAY_WORDS:
        await _my_pay(worker, reply)
        return

    if not lowered or lowered in _MENU_WORDS:
        day = attendance.get_day(worker["worker_id"], today)
        status = f"Today you're marked *{STATUS_LABELS[day['status']]}*." if day else "You haven't checked in today."
        await reply.buttons(f"👋 Hello {first}! {status}\n\nWhat would you like to do?", MENU)
        return

    ot = _OT_RE.search(text)
    if ot:
        hours = float(ot.group(1) or ot.group(2))
        attendance.worker_claim_ot(worker, hours, today)
        evidence.add_note(worker, today, text)
        await reply.text(f"⏱️ Noted: you're claiming *{hours:g}h overtime* today. Your supervisor "
                         "will confirm it. A photo of the extra work helps.")
        return

    attendance.worker_check_in(worker, today)
    evidence.add_note(worker, today, text)
    await reply.text("📝 Saved as today's work note for your supervisor. Send a photo too if you can.")


async def _check_in(worker: dict, today: str, reply: whatsapp.Replier) -> None:
    result = attendance.worker_check_in(worker, today)
    first = worker["name"].split()[0]
    if result["created"]:
        msg = f"✅ Checked in, {first}. You're marked *Present* for today."
    else:
        status = STATUS_LABELS[result["day"]["status"]]
        msg = f"✅ You're already on today's register as *{status}*, {first}."
    await reply.buttons(msg + "\n\nSend a photo of your work during or after the job.", [BTN_PHOTO, BTN_PAY])


async def _photo(worker: dict, today: str, image_bytes: bytes, caption: str,
                 reply: whatsapp.Replier, wait_for_ai: bool) -> None:
    try:
        ev = evidence.add_photo(worker, today, image_bytes, caption or "")
    except evidence.ImageError as e:
        logger.warning(f"Photo from {worker['phone']} unreadable: {e}")
        await reply.text("I couldn't open that photo. Please send it again.")
        return
    whatsapp.log_inbound(worker["phone"], f"[photo] {caption}".strip(), ev["evidence_id"])
    result = attendance.worker_check_in(worker, today)

    count = len([e for e in evidence.for_worker_day(worker["worker_id"], today) if e["kind"] == "photo"])
    lines = [f"📸 Photo received ({count} today). Your supervisor will see it with today's register."]
    if result["created"]:
        lines.append("✅ You're also checked in as *Present* for today.")
    if "too_dark" in ev["flags"]:
        lines.append("💡 It looks quite dark. If you can, send another one in better light.")
    if "duplicate_other_day" in ev["flags"]:
        lines.append("⚠️ This looks like a photo sent on another day. Please send a fresh photo of today's work.")
    elif "duplicate_same_day" in ev["flags"]:
        lines.append("ℹ️ This looks the same as a photo you already sent today.")
    await reply.text("\n".join(lines))

    task = asyncio.create_task(summarise(ev["evidence_id"], caption or "", worker.get("trade", "")))
    if wait_for_ai:
        await task
    else:
        _ai_tasks().add(task)
        task.add_done_callback(_ai_tasks().discard)


async def summarise(evidence_id: str, caption: str, trade: str) -> dict:
    jpeg = evidence.get_photo_bytes(evidence_id)
    if not jpeg:
        return {}
    result = await ai.summarise_photo(jpeg, caption, trade)
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
