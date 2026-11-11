"""
AI helpers, all advisory. Nothing here decides pay or writes to the register.

  summarise_photo(...)   vision: what work a site photo shows, for the supervisor
  parse_register(...)    turn a messy pasted/dictated register into rows the
                         supervisor reviews before applying

Any OpenAI-compatible endpoint works (LLM_BASE_URL / LLM_MODEL). When AI is
not configured, or a call fails, each function returns a clearly-marked
"unavailable" result and the product still works: the supervisor just looks
at the photo themselves.
"""

import base64
import json
import logging
import re
from typing import List, Optional

import config

logger = logging.getLogger(__name__)

SCENE_TYPES = (
    "blockwork", "plastering", "foundation", "concrete", "roofing", "painting", "electrical",
    "plumbing", "tiling", "carpentry", "loading", "farm", "cleaning", "other",
)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY or "none",
                              timeout=90, max_retries=1)
    return _client


def extract_json(text: str) -> Optional[dict]:
    """Forgiving JSON extraction (fenced, bare, or embedded in prose)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            return None
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    break
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
        except json.JSONDecodeError:
            return None


async def _chat(system: str, user_content, model: str) -> Optional[dict]:
    resp = await _get_client().chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}],
    )
    return extract_json(resp.choices[0].message.content or "")


# ── Photo evidence ───────────────────────────────────────────────────────────

_PHOTO_PROMPT = f"""You review work photos for SitePay, a day-labour payroll tool used on construction sites, farms and loading yards in Nigeria.

A worker sent this photo as proof of the work they did today. Describe what the photo shows so their supervisor can approve the day quickly. You do NOT decide pay and you never accuse anyone; you only describe.

Return ONE JSON object, nothing else:
{{
  "scene_type": one of {list(SCENE_TYPES)},
  "is_work_related": true/false,
  "progress": "one short phrase on visible progress, e.g. 'wall section appears completed', 'materials stacked, work not started'",
  "summary": "one plain sentence (max 25 words) a busy supervisor can read at a glance",
  "image_quality": "good" | "dark" | "blurry" | "too_far",
  "confidence": "high" | "medium" | "low"
}}

Rules:
- is_work_related is false only if the photo clearly shows nothing to do with site or farm work (a selfie in a room, a screenshot, a meme, etc.).
- Describe only what is visible. Don't guess how many hours were worked or whether the worker was present all day.
- If the worker's caption or trade is given, use it as context, but don't repeat it as fact if the photo doesn't support it."""


def unavailable(reason: str) -> dict:
    return {"ok": False, "reason": reason, "summary": "", "flags": []}


async def summarise_photo(jpeg: bytes, caption: str = "", trade: str = "") -> dict:
    if not config.AI_ENABLED:
        return unavailable("AI not configured")
    context = []
    if trade:
        context.append(f"Worker's trade: {trade}.")
    context.append(f'Worker caption: "{caption.strip()}".' if caption.strip() else "No caption.")
    content = [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
        {"type": "text", "text": " ".join(context) + " Return the JSON object."},
    ]
    try:
        parsed = await _chat(_PHOTO_PROMPT, content, config.LLM_VISION_MODEL)
    except Exception as e:
        logger.error(f"❌ Vision call failed: {e}")
        return unavailable("AI call failed")
    if not parsed:
        return unavailable("AI reply unreadable")

    scene = str(parsed.get("scene_type", "other")).lower()
    quality = str(parsed.get("image_quality", "good")).lower()
    flags = []
    if parsed.get("is_work_related") is False:
        flags.append("unrelated")
    if quality in ("dark", "blurry", "too_far"):
        flags.append(f"quality_{quality}")
    return {
        "ok": True,
        "scene_type": scene if scene in SCENE_TYPES else "other",
        "is_work_related": parsed.get("is_work_related") is not False,
        "progress": str(parsed.get("progress", ""))[:160],
        "summary": str(parsed.get("summary", ""))[:300],
        "image_quality": quality,
        "confidence": str(parsed.get("confidence", "medium")).lower(),
        "flags": flags,
    }


# ── Messy register → structured rows ─────────────────────────────────────────

_REGISTER_PROMPT = """You convert a site supervisor's messy attendance notes into structured rows for SitePay.

Status codes: P = present full day, A = absent, H = half day, OT = present with overtime, L = paid leave.

Return ONE JSON object, nothing else:
{"rows": [{"worker": "name as written", "status": "P|A|H|OT|L", "ot_hours": number, "advance": number, "notes": "short note or empty"}]}

Rules:
- Only include workers actually mentioned. Never invent a worker or a status.
- If a worker is mentioned but the status is unclear, use "P" only if the text clearly implies they worked; otherwise skip them.
- "left early", "left 1pm", "half" → H. "2 hours extra", "+2 OT" → OT with ot_hours 2.
- advance is money given to the worker in advance (e.g. "collected 1k" → 1000). Use plain numbers; "1k" = 1000.
- Keep any extra detail (e.g. "left 1pm") in notes."""


def _match_worker(name: str, workers: List[dict]) -> Optional[dict]:
    target = re.sub(r"[^a-z ]", "", name.lower()).split()
    if not target:
        return None
    best, best_score = None, 0
    for w in workers:
        parts = re.sub(r"[^a-z ]", "", w["name"].lower()).split()
        score = 0
        if parts and parts[0] == target[0]:
            score += 2
        score += len(set(target) & set(parts))
        if score > best_score:
            best, best_score = w, score
    return best if best_score >= 2 else None


def _num(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").lower().replace(",", "").strip()
    mult = 1000 if text.endswith("k") else 1
    try:
        return float(text.rstrip("k") or 0) * mult
    except ValueError:
        return 0.0


async def parse_register(text: str, workers: List[dict]) -> dict:
    """Returns {"ok", "rows": [{worker_id, worker_name, matched_from, status, ot_hours, advance, notes}],
    "unmatched": [names]}. The caller shows these for review; nothing is saved here."""
    if not config.AI_ENABLED:
        return {"ok": False, "reason": "AI not configured", "rows": [], "unmatched": []}
    roster = ", ".join(w["name"] for w in workers)
    try:
        parsed = await _chat(_REGISTER_PROMPT, f"Crew on this site: {roster}\n\nNotes:\n{text[:4000]}",
                             config.LLM_MODEL)
    except Exception as e:
        logger.error(f"❌ Register parse failed: {e}")
        return {"ok": False, "reason": "AI call failed", "rows": [], "unmatched": []}
    if not parsed or not isinstance(parsed.get("rows"), list):
        return {"ok": False, "reason": "AI reply unreadable", "rows": [], "unmatched": []}

    rows, unmatched = [], []
    for raw in parsed["rows"]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("worker", "")).strip()
        worker = _match_worker(name, workers)
        if not worker:
            if name:
                unmatched.append(name)
            continue
        status = str(raw.get("status", "P")).upper()
        if status not in ("P", "A", "H", "OT", "L"):
            continue
        ot = max(0.0, min(_num(raw.get("ot_hours")), 12.0))
        rows.append({
            "worker_id": worker["worker_id"],
            "worker_name": worker["name"],
            "matched_from": name,
            "status": "OT" if status == "P" and ot > 0 else status,
            "ot_hours": ot,
            "advance": int(max(0.0, _num(raw.get("advance")))),
            "notes": str(raw.get("notes", ""))[:200],
        })
    return {"ok": True, "rows": rows, "unmatched": unmatched}
