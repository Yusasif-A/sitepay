"""
WhatsApp Cloud API transport (adapted from Avalio's app.py), plus the
"replier" abstraction that lets the same bot logic answer either a real
WhatsApp user or the dashboard's built-in WhatsApp simulator.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import logging
from typing import List, Optional

import httpx

import config
from accounts import now
from db import get_db

logger = logging.getLogger(__name__)

GRAPH_API = f"https://graph.facebook.com/{config.WHATSAPP_GRAPH_VERSION}"


def configured() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}", "Content-Type": "application/json"}


async def _post(body: dict) -> bool:
    if not configured():
        logger.info(f"(WhatsApp not configured) would send to {body.get('to')}: {str(body)[:160]}")
        return False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{GRAPH_API}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages",
                                     headers=_headers(), json={"messaging_product": "whatsapp", **body})
        if resp.status_code != 200:
            logger.error(f"❌ WhatsApp send to {body.get('to')} failed: {resp.status_code} {resp.text[:300]}")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ WhatsApp send errored: {e}")
        return False


async def download_media(media_id: str) -> bytes:
    """Two-step: look up the media URL, then download it with the token."""
    auth = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        meta = await client.get(f"{GRAPH_API}/{media_id}", headers=auth)
        meta.raise_for_status()
        media = await client.get(meta.json()["url"], headers=auth)
        media.raise_for_status()
        return media.content


async def mark_read(message_id: str) -> None:
    if message_id:
        await _post({"status": "read", "message_id": message_id})


def _log(phone: str, direction: str, text: str, buttons: Optional[List[dict]] = None,
         image_evidence_id: Optional[str] = None) -> None:
    """Every message in and out is kept in `chat_log` so the simulator (and
    the supervisor) can see the conversation."""
    get_db().chat_log.insert_one({
        "phone": phone, "direction": direction, "text": text,
        "buttons": buttons or [], "evidence_id": image_evidence_id, "at": now(),
    })


class Replier:
    """Sends replies to one phone number."""

    def __init__(self, phone: str, simulated: bool):
        self.phone = phone
        self.simulated = simulated

    async def text(self, body: str) -> None:
        _log(self.phone, "out", body)
        if not self.simulated:
            await _post({"to": self.phone, "type": "text", "text": {"body": body}})

    async def buttons(self, body: str, buttons: List[dict]) -> None:
        _log(self.phone, "out", body, buttons)
        if self.simulated:
            return
        await _post({"to": self.phone, "type": "interactive", "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
                                   for b in buttons[:3]]},
        }})


async def notify(phone: str, body: str) -> bool:
    """Outbound message the worker didn't just prompt (the pay note).

    Free-form text only delivers inside WhatsApp's 24-hour window. If a
    template is configured we use it, which works any time."""
    _log(phone, "out", body)
    if not configured():
        return False
    if config.WHATSAPP_PAYNOTE_TEMPLATE:
        return await _post({"to": phone, "type": "template", "template": {
            "name": config.WHATSAPP_PAYNOTE_TEMPLATE,
            "language": {"code": config.WHATSAPP_TEMPLATE_LANG},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": body.replace("\n", " ")[:1000]}]}],
        }})
    return await _post({"to": phone, "type": "text", "text": {"body": body}})


def log_inbound(phone: str, text: str, evidence_id: Optional[str] = None) -> None:
    _log(phone, "in", text, image_evidence_id=evidence_id)


def chat_history(phone: str, limit: int = 100) -> List[dict]:
    rows = list(get_db().chat_log.find({"phone": phone}).sort([("at", -1), ("_id", -1)]).limit(limit))
    rows.reverse()
    return [{k: v for k, v in r.items() if k != "_id"} for r in rows]
