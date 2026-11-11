"""
Work evidence: photos and notes a worker sends on WhatsApp (or a supervisor
uploads), attached to a worker-day.

Photos are cleaned before they're stored: re-encoded so EXIF/GPS metadata is
gone (the same approach as Avalio's anonymiser) and shrunk to at most
1280px. Two checks are deterministic, not AI, because they need to be
reliable rather than clever:

  * too_dark   - mean brightness below a threshold
  * duplicate  - perceptual (average) hash close to one of this worker's
                 earlier photos, i.e. the same picture sent again on
                 another day

The AI summary (ai.py) is added afterwards and is advisory only.
"""

import io
import logging
from typing import List, Optional, Tuple

from bson import Binary

from accounts import new_id, now
from db import get_db

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageStat
    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    PIL_AVAILABLE = False

MAX_SIDE = 1280
DARK_THRESHOLD = 40          # mean luminance 0-255
DUPLICATE_MAX_DISTANCE = 4   # bits differing out of 64


class ImageError(Exception):
    pass


def clean_image(image_bytes: bytes) -> Tuple[bytes, dict]:
    """Returns (jpeg_bytes, facts). Raises ImageError if it can't be decoded,
    because an image we can't strip metadata from is never stored."""
    if not PIL_AVAILABLE:
        raise ImageError("Pillow is not installed")
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            rgb = img.convert("RGB")
    except Exception as e:
        raise ImageError(f"Could not read image: {e}")

    rgb.thumbnail((MAX_SIDE, MAX_SIDE))
    # A fresh image holds pixels only, so no EXIF/GPS/XMP survives.
    clean = Image.new("RGB", rgb.size)
    clean.paste(rgb)

    brightness = ImageStat.Stat(clean.convert("L")).mean[0]
    out = io.BytesIO()
    clean.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), {
        "width": clean.width,
        "height": clean.height,
        "brightness": round(brightness, 1),
        "ahash": average_hash(clean),
    }


def average_hash(img) -> str:
    """64-bit difference hash: compares each pixel with its right neighbour on
    a 9×8 thumbnail. Survives WhatsApp recompression and resizing of the same
    photo, but tells apart two different photos of similar scenes far better
    than a plain average hash."""
    small = img.convert("L").resize((9, 8))
    bits = "".join(
        "1" if small.getpixel((x, y)) > small.getpixel((x + 1, y)) else "0"
        for y in range(8) for x in range(8)
    )
    return f"{int(bits, 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _find_duplicate(worker_id: str, ahash: str, day: str) -> Optional[dict]:
    cursor = get_db().evidence.find(
        {"worker_id": worker_id, "kind": "photo", "ahash": {"$exists": True}},
        {"evidence_id": 1, "date": 1, "ahash": 1},
    ).sort("created_at", -1).limit(200)
    for doc in cursor:
        if hamming(doc["ahash"], ahash) <= DUPLICATE_MAX_DISTANCE:
            return {"evidence_id": doc["evidence_id"], "date": doc["date"], "same_day": doc["date"] == day}
    return None


def add_photo(worker: dict, day: str, image_bytes: bytes, caption: str = "",
              source: str = "whatsapp") -> dict:
    jpeg, facts = clean_image(image_bytes)
    flags: List[str] = []
    duplicate = _find_duplicate(worker["worker_id"], facts["ahash"], day)
    if duplicate:
        flags.append("duplicate_same_day" if duplicate["same_day"] else "duplicate_other_day")
    if facts["brightness"] < DARK_THRESHOLD:
        flags.append("too_dark")

    doc = {
        "evidence_id": new_id("EV"),
        "worker_id": worker["worker_id"],
        "supervisor_id": worker["supervisor_id"],
        "site_id": worker["site_id"],
        "date": day,
        "kind": "photo",
        "purpose": "work",
        "text": (caption or "").strip()[:500],
        "image": Binary(jpeg),
        "ahash": facts["ahash"],
        "brightness": facts["brightness"],
        "duplicate_of": duplicate,
        "flags": flags,
        "ai": None,
        "source": source,
        "created_at": now(),
    }
    get_db().evidence.insert_one(doc)
    return public(doc)


def add_note(worker: dict, day: str, text: str, kind: str = "text", source: str = "whatsapp") -> dict:
    doc = {
        "evidence_id": new_id("EV"),
        "worker_id": worker["worker_id"],
        "supervisor_id": worker["supervisor_id"],
        "site_id": worker["site_id"],
        "date": day,
        "kind": kind,  # text
        "text": text.strip()[:1000],
        "flags": [],
        "ai": None,
        "source": source,
        "created_at": now(),
    }
    get_db().evidence.insert_one(doc)
    return public(doc)


def set_purpose(evidence_id: str, purpose: str) -> None:
    """'check_in' for the photo that completed check-in, 'work' otherwise."""
    get_db().evidence.update_one({"evidence_id": evidence_id}, {"$set": {"purpose": purpose}})


_AI_FLAGS = {"unrelated", "not_on_site", "no_person", "timestamp_mismatch",
             "quality_dark", "quality_blurry", "quality_too_far"}


def set_ai(evidence_id: str, ai_result: dict) -> None:
    """Store the AI result. A re-run replaces the previous AI flags; the
    deterministic ones (too dark, duplicate) are kept."""
    doc = get_db().evidence.find_one({"evidence_id": evidence_id}, {"flags": 1})
    kept = {f for f in (doc or {}).get("flags", []) if f not in _AI_FLAGS}
    update = {"ai": ai_result, "flags": sorted(kept | set(ai_result.get("flags") or []))}
    get_db().evidence.update_one({"evidence_id": evidence_id}, {"$set": update})


def public(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return None
    out = {k: v for k, v in doc.items() if k not in ("_id", "image", "ahash")}
    out["has_image"] = doc.get("kind") == "photo"
    return out


def for_days(supervisor_id: str, site_id: str, days: List[str]) -> List[dict]:
    cursor = get_db().evidence.find(
        {"supervisor_id": supervisor_id, "site_id": site_id, "date": {"$in": days}},
        {"image": 0},
    ).sort("created_at", 1)
    return [public(d) for d in cursor]


def for_worker_day(worker_id: str, day: str) -> List[dict]:
    cursor = get_db().evidence.find({"worker_id": worker_id, "date": day}, {"image": 0}).sort("created_at", 1)
    return [public(d) for d in cursor]


def get_image(supervisor_id: str, evidence_id: str) -> Optional[bytes]:
    doc = get_db().evidence.find_one({"supervisor_id": supervisor_id, "evidence_id": evidence_id}, {"image": 1})
    if not doc or "image" not in doc:
        return None
    return bytes(doc["image"])


def get_photo_bytes(evidence_id: str) -> Optional[bytes]:
    doc = get_db().evidence.find_one({"evidence_id": evidence_id}, {"image": 1})
    return bytes(doc["image"]) if doc and "image" in doc else None
