"""
Supervisors, sites and workers.

A supervisor signs up on the dashboard, creates one or more sites, and adds
the crew by phone number. The phone number is how the WhatsApp bot knows
who is messaging, so it's normalised to WhatsApp's international digits-only
form (2348012345678) and kept unique across all of SitePay.
"""

import re
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from pymongo.errors import DuplicateKeyError

import config
from auth import hash_password, verify_password
from db import get_db
from payroll import default_ot_rate


class AccountError(Exception):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


def now() -> datetime:
    return datetime.now(timezone.utc)


def _public(doc: Optional[dict], *hidden: str) -> Optional[dict]:
    if not doc:
        return None
    return {k: v for k, v in doc.items() if k != "_id" and k not in hidden}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = config.DEFAULT_COUNTRY_CODE + digits[1:]
    if not 8 <= len(digits) <= 15:
        raise AccountError("Enter a valid phone number, e.g. 0803 123 4567 or +234 803 123 4567")
    return digits


# ── Supervisors ──────────────────────────────────────────────────────────────

def create_supervisor(name: str, email: str, password: str, company: str = "", phone: str = "") -> dict:
    email = (email or "").strip().lower()
    if not name.strip():
        raise AccountError("Enter your name")
    if not _EMAIL_RE.match(email):
        raise AccountError("Enter a valid email address")
    if len(password or "") < 8:
        raise AccountError("Password must be at least 8 characters")
    doc = {
        "supervisor_id": new_id("SUP"),
        "name": name.strip(),
        "company": company.strip(),
        "email": email,
        "phone": normalise_phone(phone) if phone.strip() else "",
        "password_hash": hash_password(password),
        "created_at": now(),
    }
    try:
        get_db().supervisors.insert_one(doc)
    except DuplicateKeyError:
        raise AccountError("An account with this email already exists. Sign in instead.")
    return _public(doc, "password_hash")


def authenticate(email: str, password: str) -> dict:
    doc = get_db().supervisors.find_one({"email": (email or "").strip().lower()})
    if not doc or not verify_password(password, doc.get("password_hash", "")):
        raise AccountError("Wrong email or password")
    return _public(doc, "password_hash")


def get_supervisor(supervisor_id: str) -> Optional[dict]:
    return _public(get_db().supervisors.find_one({"supervisor_id": supervisor_id}), "password_hash")


# ── Sites ────────────────────────────────────────────────────────────────────

def create_site(supervisor_id: str, name: str, location: str = "") -> dict:
    if not name.strip():
        raise AccountError("Give the site a name")
    doc = {
        "site_id": new_id("SITE"),
        "supervisor_id": supervisor_id,
        "name": name.strip()[:80],
        "location": location.strip()[:120],
        "active": True,
        "created_at": now(),
    }
    get_db().sites.insert_one(doc)
    return _public(doc)


def list_sites(supervisor_id: str) -> List[dict]:
    return [_public(d) for d in get_db().sites.find({"supervisor_id": supervisor_id}).sort("created_at", 1)]


def get_site(supervisor_id: str, site_id: str) -> Optional[dict]:
    return _public(get_db().sites.find_one({"supervisor_id": supervisor_id, "site_id": site_id}))


def update_site(supervisor_id: str, site_id: str, fields: dict) -> Optional[dict]:
    allowed = {k: v for k, v in fields.items() if k in ("name", "location", "active")}
    if allowed:
        get_db().sites.update_one({"supervisor_id": supervisor_id, "site_id": site_id}, {"$set": allowed})
    return get_site(supervisor_id, site_id)


# ── Workers ──────────────────────────────────────────────────────────────────

def _check_worker_fields(fields: dict) -> dict:
    out = {}
    if "name" in fields:
        if not str(fields["name"]).strip():
            raise AccountError("Enter the worker's name")
        out["name"] = str(fields["name"]).strip()[:80]
    if "trade" in fields:
        out["trade"] = str(fields["trade"] or "").strip()[:40]
    if "phone" in fields:
        out["phone"] = normalise_phone(fields["phone"])
    if "daily_rate" in fields:
        rate = int(fields["daily_rate"])
        if rate < 0:
            raise AccountError("Daily rate can't be negative")
        out["daily_rate"] = rate
    if "ot_rate" in fields and fields["ot_rate"] is not None:
        if int(fields["ot_rate"]) < 0:
            raise AccountError("OT rate can't be negative")
        out["ot_rate"] = int(fields["ot_rate"])
    if "paypal_email" in fields:
        email = str(fields["paypal_email"] or "").strip().lower()
        if email and not _EMAIL_RE.match(email):
            raise AccountError("PayPal email doesn't look valid")
        out["paypal_email"] = email
    if "site_id" in fields:
        out["site_id"] = fields["site_id"]
    if "active" in fields:
        out["active"] = bool(fields["active"])
    return out


def create_worker(supervisor_id: str, **fields) -> dict:
    data = _check_worker_fields(fields)
    for required in ("name", "phone", "daily_rate", "site_id"):
        if required not in data:
            raise AccountError(f"Missing {required.replace('_', ' ')}")
    if not get_site(supervisor_id, data["site_id"]):
        raise AccountError("Pick one of your sites")
    data.setdefault("ot_rate", default_ot_rate(data["daily_rate"]))
    data.setdefault("trade", "")
    data.setdefault("paypal_email", "")
    doc = {
        "worker_id": new_id("W"),
        "supervisor_id": supervisor_id,
        "active": True,
        "created_at": now(),
        **data,
    }
    try:
        get_db().workers.insert_one(doc)
    except DuplicateKeyError:
        raise AccountError("A worker with this phone number is already registered on SitePay")
    return _public(doc)


def update_worker(supervisor_id: str, worker_id: str, fields: dict) -> dict:
    data = _check_worker_fields(fields)
    if "site_id" in data and not get_site(supervisor_id, data["site_id"]):
        raise AccountError("Pick one of your sites")
    try:
        result = get_db().workers.update_one(
            {"supervisor_id": supervisor_id, "worker_id": worker_id}, {"$set": data},
        )
    except DuplicateKeyError:
        raise AccountError("Another worker already uses this phone number")
    if not result.matched_count:
        raise AccountError("Worker not found")
    return get_worker(supervisor_id, worker_id)


def list_workers(supervisor_id: str, site_id: Optional[str] = None, active_only: bool = False) -> List[dict]:
    query = {"supervisor_id": supervisor_id}
    if site_id:
        query["site_id"] = site_id
    if active_only:
        query["active"] = True
    return [_public(d) for d in get_db().workers.find(query).sort("name", 1)]


def get_worker(supervisor_id: str, worker_id: str) -> Optional[dict]:
    return _public(get_db().workers.find_one({"supervisor_id": supervisor_id, "worker_id": worker_id}))


def find_worker_by_phone(phone: str) -> Optional[dict]:
    try:
        phone = normalise_phone(phone)
    except AccountError:
        return None
    return _public(get_db().workers.find_one({"phone": phone, "active": True}))
