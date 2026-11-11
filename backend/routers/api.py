"""
Supervisor dashboard API: /api/*.

Public:   POST /api/auth/signup, POST /api/auth/login
Everything else needs a supervisor JWT and only ever touches that
supervisor's own sites, workers and pay runs.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

import accounts
import ai
import attendance
import bot
import config
import evidence
import payruns
import whatsapp
from accounts import AccountError
from auth import create_token, require_supervisor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except attendance.LockedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── Auth ─────────────────────────────────────────────────────────────────────

class SignupBody(BaseModel):
    name: str
    email: str
    password: str
    company: str = ""
    phone: str = ""
    site_name: str = ""
    site_location: str = ""


@router.post("/auth/signup")
def signup(body: SignupBody):
    sup = _guard(accounts.create_supervisor, body.name, body.email, body.password, body.company, body.phone)
    if body.site_name.strip():
        _guard(accounts.create_site, sup["supervisor_id"], body.site_name, body.site_location)
    return {"token": create_token(sup["supervisor_id"]), "supervisor": sup}


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginBody):
    try:
        sup = accounts.authenticate(body.email, body.password)
    except AccountError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"token": create_token(sup["supervisor_id"]), "supervisor": sup}


@router.get("/me")
def me(sid: str = Depends(require_supervisor)):
    sup = accounts.get_supervisor(sid)
    if not sup:
        raise HTTPException(status_code=401, detail="Account not found")
    return {
        "supervisor": sup,
        "sites": accounts.list_sites(sid),
        "settings": {
            "wage_currency": config.WAGE_CURRENCY,
            "payout_currency": config.PAYOUT_CURRENCY,
            "fx_rate": config.PAYOUT_FX_RATE,
            "paypal_env": config.PAYPAL_ENV,
            "paypal_simulated": payruns.simulate_mode(),
            "ai_enabled": config.AI_ENABLED,
            "whatsapp_live": whatsapp.configured(),
            "today": attendance.today(),
        },
    }


# ── Sites ────────────────────────────────────────────────────────────────────

class SiteBody(BaseModel):
    name: str
    location: str = ""


@router.post("/sites")
def create_site(body: SiteBody, sid: str = Depends(require_supervisor)):
    return _guard(accounts.create_site, sid, body.name, body.location)


class SitePatch(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    active: Optional[bool] = None


@router.patch("/sites/{site_id}")
def update_site(site_id: str, body: SitePatch, sid: str = Depends(require_supervisor)):
    site = accounts.update_site(sid, site_id, body.model_dump(exclude_none=True))
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


# ── Workers ──────────────────────────────────────────────────────────────────

class WorkerBody(BaseModel):
    name: str
    phone: str
    site_id: str
    daily_rate: int = Field(ge=0)
    ot_rate: Optional[int] = Field(default=None, ge=0)
    trade: str = ""
    paypal_email: str = ""


@router.get("/workers")
def list_workers(site_id: Optional[str] = None, sid: str = Depends(require_supervisor)):
    return {"workers": accounts.list_workers(sid, site_id)}


@router.post("/workers")
def create_worker(body: WorkerBody, sid: str = Depends(require_supervisor)):
    return _guard(accounts.create_worker, sid, **body.model_dump(exclude_none=True))


class WorkerPatch(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    site_id: Optional[str] = None
    daily_rate: Optional[int] = Field(default=None, ge=0)
    ot_rate: Optional[int] = Field(default=None, ge=0)
    trade: Optional[str] = None
    paypal_email: Optional[str] = None
    active: Optional[bool] = None


@router.patch("/workers/{worker_id}")
def update_worker(worker_id: str, body: WorkerPatch, sid: str = Depends(require_supervisor)):
    return _guard(accounts.update_worker, sid, worker_id, body.model_dump(exclude_none=True))


# ── Register (attendance grid) ───────────────────────────────────────────────

@router.get("/register")
def get_register(site_id: str, date: str, sid: str = Depends(require_supervisor)):
    """One row per active worker for one day, with that day's evidence."""
    day = _guard(attendance.parse_date, date)
    if not accounts.get_site(sid, site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    workers = accounts.list_workers(sid, site_id, active_only=True)
    records = {d["worker_id"]: d for d in attendance.days_for_site(sid, site_id, [day])}
    ev_by_worker = {}
    for ev in evidence.for_days(sid, site_id, [day]):
        ev_by_worker.setdefault(ev["worker_id"], []).append(ev)

    rows = []
    for w in workers:
        rec = records.get(w["worker_id"])
        evs = ev_by_worker.get(w["worker_id"], [])
        flags = sorted({f for e in evs for f in e.get("flags", [])})
        rows.append({
            "worker_id": w["worker_id"],
            "name": w["name"],
            "trade": w.get("trade", ""),
            "daily_rate": (rec or w).get("daily_rate", w["daily_rate"]),
            "ot_rate": (rec or w).get("ot_rate", w.get("ot_rate", 0)),
            "logged": rec is not None,
            "status": rec["status"] if rec else None,
            "ot_hours": rec["ot_hours"] if rec else 0,
            "ot_claim_hours": rec.get("ot_claim_hours", 0) if rec else 0,
            "advance": rec["advance"] if rec else 0,
            "notes": rec["notes"] if rec else "",
            "review": rec["review"] if rec else None,
            "source": rec["source"] if rec else None,
            "checked_in": bool(rec and rec.get("check_in_at")),
            "has_location": bool(rec and rec.get("check_in_location")),
            "pay_run_id": rec.get("pay_run_id") if rec else None,
            "photo_count": sum(1 for e in evs if e["kind"] == "photo"),
            "evidence": evs,
            "flags": flags,
        })
    return {"date": day, "rows": rows}


class DayPatch(BaseModel):
    status: Optional[str] = None
    ot_hours: Optional[float] = None
    advance: Optional[int] = None
    notes: Optional[str] = None
    review: Optional[str] = None


@router.put("/register/{worker_id}/{date}")
def set_day(worker_id: str, date: str, body: DayPatch, sid: str = Depends(require_supervisor)):
    return _guard(attendance.supervisor_set_day, sid, worker_id, date, body.model_dump(exclude_none=True))


class BulkBody(BaseModel):
    site_id: str
    date: str
    worker_ids: List[str]
    status: Optional[str] = None
    review: Optional[str] = None


@router.post("/register/bulk")
def bulk_set(body: BulkBody, sid: str = Depends(require_supervisor)):
    updated, skipped = 0, []
    for wid in body.worker_ids:
        try:
            attendance.supervisor_set_day(sid, wid, body.date, {"status": body.status, "review": body.review})
            updated += 1
        except AccountError as e:
            skipped.append(str(e))
    return {"updated": updated, "skipped": skipped}


class NeedsPhotoBody(BaseModel):
    message: str = ""


@router.post("/register/{worker_id}/{date}/request-photo")
async def request_photo(worker_id: str, date: str, body: NeedsPhotoBody, sid: str = Depends(require_supervisor)):
    worker = accounts.get_worker(sid, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    await run_in_threadpool(_guard, attendance.supervisor_set_day, sid, worker_id, date, {"review": "needs_photo"})
    text = ("📸 *Your supervisor asked for a clearer photo* of your work on "
            f"{payruns.period_label(date, date)}." + (f"\n\n_{body.message.strip()}_" if body.message.strip() else "")
            + "\n\nPlease send it here.")
    delivered = await whatsapp.notify(worker["phone"], text)
    return {"ok": True, "delivered": delivered}


class ParseBody(BaseModel):
    site_id: str
    text: str = Field(min_length=2, max_length=4000)


@router.post("/register/parse")
async def parse_register(body: ParseBody, sid: str = Depends(require_supervisor)):
    """AI reads messy notes into rows for review. Nothing is saved."""
    workers = accounts.list_workers(sid, body.site_id, active_only=True)
    return await ai.parse_register(body.text, workers)


# ── Evidence ─────────────────────────────────────────────────────────────────

@router.get("/evidence/{evidence_id}/image")
def evidence_image(evidence_id: str, sid: str = Depends(require_supervisor)):
    data = evidence.get_image(sid, evidence_id)
    if not data:
        raise HTTPException(status_code=404, detail="Photo not found")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/evidence/upload")
async def upload_evidence(worker_id: str = Form(...), date: str = Form(...), caption: str = Form(""),
                          file: UploadFile = File(...), sid: str = Depends(require_supervisor)):
    """Supervisor uploads a photo for a worker (fallback when the worker has no smartphone)."""
    worker = accounts.get_worker(sid, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    day = _guard(attendance.parse_date, date)
    data = await file.read()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Photo is too large (max 12 MB)")
    try:
        ev = evidence.add_photo(worker, day, data, caption, source="dashboard")
    except evidence.ImageError:
        raise HTTPException(status_code=422, detail="That file isn't a readable image")
    result = await bot.summarise(ev["evidence_id"], caption, worker.get("trade", ""))
    return {**ev, "ai": result}


@router.post("/evidence/{evidence_id}/reanalyse")
async def reanalyse(evidence_id: str, sid: str = Depends(require_supervisor)):
    if not evidence.get_image(sid, evidence_id):
        raise HTTPException(status_code=404, detail="Photo not found")
    return await bot.summarise(evidence_id, "", "")


# ── Pay runs ─────────────────────────────────────────────────────────────────

@router.get("/payruns/preview")
def preview(site_id: str, start: str, end: str, sid: str = Depends(require_supervisor)):
    return _guard(payruns.preview, sid, site_id, start, end)


class ApproveBody(BaseModel):
    site_id: str
    start: str
    end: str
    worker_ids: Optional[List[str]] = None


@router.post("/payruns")
def approve(body: ApproveBody, sid: str = Depends(require_supervisor)):
    return _guard(payruns.approve, sid, body.site_id, body.start, body.end, body.worker_ids)


@router.get("/payruns")
def list_runs(sid: str = Depends(require_supervisor)):
    return {"runs": payruns.list_runs(sid)}


@router.get("/payruns/{run_id}")
def get_run(run_id: str, sid: str = Depends(require_supervisor)):
    run = payruns.get_run(sid, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    return run


async def _refresh_and_notify(sid: str, run_id: str) -> dict:
    result = await run_in_threadpool(_guard, payruns.refresh, sid, run_id)
    run = result["run"]
    for line in result["newly_paid"]:
        await whatsapp.notify(line["phone"], payruns.pay_note_whatsapp(run, line))
        payruns.mark_notified(run_id, line["worker_id"])
    if result["newly_paid"]:
        run = payruns.get_run(sid, run_id)
    return run


@router.post("/payruns/{run_id}/pay")
async def pay(run_id: str, sid: str = Depends(require_supervisor)):
    await run_in_threadpool(_guard, payruns.pay, sid, run_id)
    # Sandbox batches usually settle in seconds; one immediate refresh makes
    # the demo show SUCCESS without waiting for the next poll.
    try:
        return await _refresh_and_notify(sid, run_id)
    except HTTPException:
        return payruns.get_run(sid, run_id)


@router.post("/payruns/{run_id}/refresh")
async def refresh(run_id: str, sid: str = Depends(require_supervisor)):
    return await _refresh_and_notify(sid, run_id)


# ── WhatsApp simulator (demo without a Meta app) ─────────────────────────────

@router.get("/simulator/{worker_id}")
def sim_history(worker_id: str, sid: str = Depends(require_supervisor)):
    worker = accounts.get_worker(sid, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"worker": worker, "messages": whatsapp.chat_history(worker["phone"])}


@router.post("/simulator/{worker_id}")
async def sim_send(worker_id: str, text: str = Form(""), button_id: str = Form(""),
                   lat: Optional[float] = Form(None), lon: Optional[float] = Form(None),
                   file: Optional[UploadFile] = File(None), sid: str = Depends(require_supervisor)):
    """Act as the worker's phone: the same bot code as the real webhook."""
    worker = accounts.get_worker(sid, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    phone = worker["phone"]
    reply = whatsapp.Replier(phone, simulated=True)
    image = await file.read() if file is not None else None
    location = {"lat": lat, "lon": lon} if lat is not None and lon is not None else None

    if image is None:
        label = text or {"check_in": "✅ Check in", "send_photo": "📸 Work photo",
                         "my_pay": "💰 My pay"}.get(button_id, button_id) or ("📍 Location" if location else "")
        whatsapp.log_inbound(phone, label)
    await bot.handle(phone, reply, text=text, button_id=button_id, image_bytes=image,
                     location=location, wait_for_ai=True)
    return {"messages": whatsapp.chat_history(phone)}


# ── Demo data ────────────────────────────────────────────────────────────────

@router.post("/demo/seed")
def seed_demo(sid: str = Depends(require_supervisor)):
    import demo
    return demo.seed_for(sid)
