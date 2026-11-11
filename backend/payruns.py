"""
Pay runs: approve a period's register, then pay it through PayPal Payouts.

    draft  → preview(), recomputed live from the register, nothing saved
    approve() → run saved as "approved"; every included day is locked
                (pay_run_id set) so it can't be edited or paid twice
    pay()     → one PayPal batch, one item per worker with net > 0;
                run becomes "submitted" with the payout_batch_id
    refresh() → GET the batch; item statuses copied onto pay lines; when
                a line reaches SUCCESS the worker gets their WhatsApp pay note

The AI never calls any of this. approve() and pay() are only reachable
from authenticated supervisor endpoints.

PAYPAL_MODE=simulate (or no PayPal credentials) runs the same flow against
an in-process fake that marks every item SUCCESS. It's for rehearsing the
demo offline, and the dashboard labels those runs "SIMULATED".
"""

import logging
import os
import secrets
from datetime import date as date_cls
from typing import List, Optional

import config
import paypal
from accounts import AccountError, get_site, list_workers, new_id, now
from attendance import date_range, days_for_site
from db import get_db
from payroll import counts_phrase, summarise_worker, to_payout_amount

logger = logging.getLogger(__name__)


def simulate_mode() -> bool:
    mode = os.getenv("PAYPAL_MODE", "").strip().lower()
    if mode == "simulate":
        return True
    if mode == "live_api":
        return False
    return not paypal.get_client().configured


def _public(doc):
    return {k: v for k, v in doc.items() if k != "_id"} if doc else None


def _fmt_date(iso: str) -> str:
    d = date_cls.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def period_label(start: str, end: str) -> str:
    return _fmt_date(start) if start == end else f"{_fmt_date(start)}–{_fmt_date(end)}"


def money(amount: int) -> str:
    symbol = {"NGN": "₦", "KES": "KSh ", "INR": "₹", "GHS": "GH₵"}.get(config.WAGE_CURRENCY, "")
    return f"{symbol}{amount:,}" if symbol else f"{amount:,} {config.WAGE_CURRENCY}"


# ── Preview ──────────────────────────────────────────────────────────────────

def preview(supervisor_id: str, site_id: str, start: str, end: str) -> dict:
    site = get_site(supervisor_id, site_id)
    if not site:
        raise AccountError("Site not found")
    days = date_range(start, end)
    workers = list_workers(supervisor_id, site_id)
    by_worker = {}
    for d in days_for_site(supervisor_id, site_id, days):
        by_worker.setdefault(d["worker_id"], []).append(d)

    lines = []
    for w in workers:
        worker_days = by_worker.get(w["worker_id"], [])
        unpaid = [d for d in worker_days if not d.get("pay_run_id")]
        already_paid = len(worker_days) - len(unpaid)
        if not unpaid and not already_paid:
            continue
        summary = summarise_worker(w, unpaid)
        lines.append({
            "worker_id": w["worker_id"],
            "worker_name": w["name"],
            "trade": w.get("trade", ""),
            "phone": w["phone"],
            "paypal_email": w.get("paypal_email", ""),
            "already_paid_days": already_paid,
            "pending_review": sum(1 for d in unpaid if d.get("review") == "pending"),
            "needs_photo": sum(1 for d in unpaid if d.get("review") == "needs_photo"),
            "dates": sorted(d["date"] for d in unpaid),
            **summary,
            "payout_amount": to_payout_amount(summary["net"], config.PAYOUT_FX_RATE),
        })

    total_net = sum(l["net"] for l in lines)
    return {
        "site": site,
        "start": start,
        "end": end,
        "label": period_label(start, end),
        "wage_currency": config.WAGE_CURRENCY,
        "payout_currency": config.PAYOUT_CURRENCY,
        "fx_rate": config.PAYOUT_FX_RATE,
        "lines": lines,
        "total_net": total_net,
        "total_payout": to_payout_amount(total_net, config.PAYOUT_FX_RATE),
        "missing_paypal": [l["worker_name"] for l in lines if l["net"] > 0 and not l["paypal_email"]],
        "simulate": simulate_mode(),
    }


# ── Approve ──────────────────────────────────────────────────────────────────

def approve(supervisor_id: str, site_id: str, start: str, end: str, worker_ids: Optional[List[str]] = None) -> dict:
    """Freeze the current register into an approved pay run."""
    draft = preview(supervisor_id, site_id, start, end)
    lines = [l for l in draft["lines"] if l["days"] > 0]
    if worker_ids is not None:
        lines = [l for l in lines if l["worker_id"] in set(worker_ids)]
    if not lines:
        raise AccountError("Nothing to approve: no unpaid days in this period")
    blocked = [l["worker_name"] for l in lines if l["net"] > 0 and not l["paypal_email"]]
    if blocked:
        raise AccountError("Add a PayPal email for: " + ", ".join(blocked))

    db = get_db()
    run_id = f"RUN-{date_cls.today().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
    reference = f"{draft['site']['name']} | {draft['label']} | day labour"

    # Lock days first, and only days that are still unlocked. If another
    # approval raced us, its locked days are simply not ours.
    locked_dates = {}
    for line in lines:
        result = db.attendance.update_many(
            {"worker_id": line["worker_id"], "site_id": site_id, "date": {"$in": line["dates"]},
             "pay_run_id": None},
            {"$set": {"pay_run_id": run_id, "updated_at": now()}},
        )
        if result.modified_count != len(line["dates"]):
            # Roll back everything we locked and ask the supervisor to retry.
            db.attendance.update_many({"pay_run_id": run_id}, {"$set": {"pay_run_id": None}})
            raise AccountError("The register changed while approving. Refresh and try again.")
        locked_dates[line["worker_id"]] = line["dates"]

    run = {
        "run_id": run_id,
        "supervisor_id": supervisor_id,
        "site_id": site_id,
        "site_name": draft["site"]["name"],
        "start": start,
        "end": end,
        "label": draft["label"],
        "reference": reference,
        "status": "approved",
        "wage_currency": config.WAGE_CURRENCY,
        "payout_currency": config.PAYOUT_CURRENCY,
        "fx_rate": config.PAYOUT_FX_RATE,
        "total_net": sum(l["net"] for l in lines),
        "total_payout": to_payout_amount(sum(l["net"] for l in lines), config.PAYOUT_FX_RATE),
        "worker_count": len(lines),
        "simulated": simulate_mode(),
        "payout_batch_id": None,
        "batch_status": None,
        "error": None,
        "approved_at": now(),
        "submitted_at": None,
        "completed_at": None,
    }
    db.pay_runs.insert_one(run)

    for line in lines:
        evidence_ids = [e["evidence_id"] for e in db.evidence.find(
            {"worker_id": line["worker_id"], "date": {"$in": line["dates"]}}, {"evidence_id": 1})]
        db.pay_lines.insert_one({
            "run_id": run_id,
            "worker_id": line["worker_id"],
            "worker_name": line["worker_name"],
            "phone": line["phone"],
            "paypal_email": line["paypal_email"],
            "dates": line["dates"],
            "counts": line["counts"],
            "ot_hours": line["ot_hours"],
            "gross": line["gross"],
            "advances": line["advances"],
            "net": line["net"],
            "payout_amount": line["payout_amount"],
            "evidence_ids": evidence_ids,
            "sender_item_id": f"{run_id}-{line['worker_id']}"[:63],
            "note": pay_note_paypal(run, line),
            "payout_item_id": None,
            "transaction_id": None,
            "transaction_status": "NOT_SENT" if line["net"] > 0 else "NOTHING_DUE",
            "notified": False,
        })
    logger.info(f"✅ Pay run {run_id} approved: {len(lines)} workers, {money(run['total_net'])}")
    return get_run(supervisor_id, run_id)


def pay_note_paypal(run: dict, line: dict) -> str:
    ot = f", OT {line['ot_hours']:g}h" if line["ot_hours"] else ""
    return (f"{run['reference']}. {counts_phrase(line['counts'])}{ot}. "
            f"Gross {money(line['gross'])}, advances {money(line['advances'])}, net {money(line['net'])}.")


def pay_note_whatsapp(run: dict, line: dict) -> str:
    parts = [
        f"✅ *SitePay: you've been paid*",
        "",
        f"*{run['site_name']}*, {run['label']}",
        f"You were marked {counts_phrase(line['counts'])}"
        + (f", plus {line['ot_hours']:g}h overtime" if line["ot_hours"] else "") + ".",
        "",
        f"Gross: {money(line['gross'])}",
    ]
    if line["advances"]:
        parts.append(f"Less advances: {money(line['advances'])}")
    parts += [
        f"*Net: {money(line['net'])}*",
        f"Paid via PayPal: {line['payout_amount']} {run['payout_currency']} to {line['paypal_email']}",
        f"Ref: {run['run_id']}",
    ]
    if line.get("transaction_status") == "UNCLAIMED":
        parts += ["", "📩 Open PayPal with this email to claim it (within 30 days)."]
    if run.get("simulated"):
        parts += ["", "_(Demo: sandbox simulation, no real money moved.)_"]
    return "\n".join(parts)


# ── Pay ──────────────────────────────────────────────────────────────────────

class _SimulatedPayPal:
    """Behaves like the Payouts API, for offline demo rehearsal."""

    def create_payout(self, sender_batch_id, items, email_subject, email_message=""):
        batch_id = "SIM" + secrets.token_hex(6).upper()
        get_db().sim_payouts.insert_one({"batch_id": batch_id, "items": items, "created_at": now()})
        return {"batch_header": {"payout_batch_id": batch_id, "batch_status": "PENDING"}}

    def get_payout(self, payout_batch_id):
        doc = get_db().sim_payouts.find_one({"batch_id": payout_batch_id})
        items = [{
            "payout_item_id": f"SIMI{i:04d}{payout_batch_id[-4:]}",
            "transaction_id": f"SIMT{secrets.token_hex(5).upper()}",
            "transaction_status": "SUCCESS",
            "payout_item": {"sender_item_id": it["sender_item_id"], "receiver": it["receiver"]},
        } for i, it in enumerate((doc or {}).get("items", []))]
        return {"batch_header": {"payout_batch_id": payout_batch_id, "batch_status": "SUCCESS"}, "items": items}


def _client():
    return _SimulatedPayPal() if simulate_mode() else paypal.get_client()


def pay(supervisor_id: str, run_id: str) -> dict:
    db = get_db()
    run = db.pay_runs.find_one({"supervisor_id": supervisor_id, "run_id": run_id})
    if not run:
        raise AccountError("Pay run not found")
    if run["status"] not in ("approved", "failed"):
        raise AccountError(f"This run is already {run['status']}")

    lines = list(db.pay_lines.find({"run_id": run_id, "net": {"$gt": 0}}))
    if not lines:
        db.pay_runs.update_one({"_id": run["_id"]}, {"$set": {"status": "completed", "completed_at": now()}})
        return get_run(supervisor_id, run_id)

    items = [{
        "receiver": l["paypal_email"],
        "recipient_type": "EMAIL",
        "amount": l["payout_amount"],
        "currency": run["payout_currency"],
        "note": l["note"],
        "sender_item_id": l["sender_item_id"],
    } for l in lines]

    # Mark first so a double click can't start a second batch.
    claimed = db.pay_runs.update_one(
        {"_id": run["_id"], "status": run["status"]},
        {"$set": {"status": "submitting", "error": None}},
    )
    if not claimed.modified_count:
        raise AccountError("This run is already being paid")

    try:
        result = _client().create_payout(
            sender_batch_id=run_id,  # PayPal rejects a reuse within 30 days, so no double pay
            items=items,
            email_subject=f"You've been paid: {run['site_name']} ({run['label']})",
            email_message=f"{run['reference']}. Sent with SitePay.",
        )
    except paypal.PayPalError as e:
        db.pay_runs.update_one({"_id": run["_id"]}, {"$set": {"status": "failed", "error": str(e)}})
        logger.error(f"❌ Payout for {run_id} failed: {e} {e.details}")
        raise AccountError(str(e))

    header = result.get("batch_header", {})
    db.pay_runs.update_one({"_id": run["_id"]}, {"$set": {
        "status": "submitted",
        "payout_batch_id": header.get("payout_batch_id"),
        "batch_status": header.get("batch_status"),
        "submitted_at": now(),
    }})
    db.pay_lines.update_many({"run_id": run_id, "net": {"$gt": 0}}, {"$set": {"transaction_status": "PENDING"}})
    logger.info(f"💸 Payout batch {header.get('payout_batch_id')} submitted for {run_id}")
    return get_run(supervisor_id, run_id)


def refresh(supervisor_id: str, run_id: str) -> dict:
    """Pull status from PayPal. Returns the run plus `newly_paid` lines whose
    worker should now get a WhatsApp pay note."""
    db = get_db()
    run = db.pay_runs.find_one({"supervisor_id": supervisor_id, "run_id": run_id})
    if not run:
        raise AccountError("Pay run not found")
    if not run.get("payout_batch_id"):
        return {"run": get_run(supervisor_id, run_id), "newly_paid": []}

    try:
        batch = _client().get_payout(run["payout_batch_id"])
    except paypal.PayPalError as e:
        raise AccountError(f"Couldn't fetch status from PayPal: {e}")

    newly_paid = []
    for item in batch.get("items", []):
        sender_item_id = (item.get("payout_item") or {}).get("sender_item_id")
        line = db.pay_lines.find_one({"run_id": run_id, "sender_item_id": sender_item_id})
        if not line:
            continue
        status = item.get("transaction_status")
        db.pay_lines.update_one({"_id": line["_id"]}, {"$set": {
            "transaction_status": status,
            "payout_item_id": item.get("payout_item_id"),
            "transaction_id": item.get("transaction_id"),
            "errors": item.get("errors"),
        }})
        # UNCLAIMED = money sent, receiver has no PayPal account yet. Still
        # worth a pay note so the worker knows to claim it.
        if status in paypal.ITEM_PAID | {"UNCLAIMED"} and not line.get("notified"):
            newly_paid.append({**_public(line), "transaction_status": status})

    batch_status = batch.get("batch_header", {}).get("batch_status")
    update = {"batch_status": batch_status}
    if batch_status in paypal.BATCH_FINAL:
        update["status"] = "completed" if batch_status == "SUCCESS" else "failed"
        update["completed_at"] = now()
    db.pay_runs.update_one({"_id": run["_id"]}, {"$set": update})
    return {"run": get_run(supervisor_id, run_id), "newly_paid": newly_paid}


def mark_notified(run_id: str, worker_id: str) -> None:
    get_db().pay_lines.update_one({"run_id": run_id, "worker_id": worker_id}, {"$set": {"notified": True}})


# ── Read ─────────────────────────────────────────────────────────────────────

def get_run(supervisor_id: str, run_id: str) -> Optional[dict]:
    db = get_db()
    run = _public(db.pay_runs.find_one({"supervisor_id": supervisor_id, "run_id": run_id}))
    if not run:
        return None
    run["lines"] = [_public(l) for l in db.pay_lines.find({"run_id": run_id}).sort("worker_name", 1)]
    return run


def list_runs(supervisor_id: str) -> List[dict]:
    return [_public(r) for r in get_db().pay_runs.find({"supervisor_id": supervisor_id}).sort("approved_at", -1)]


def runs_for_worker(worker_id: str, limit: int = 3) -> List[dict]:
    db = get_db()
    out = []
    for line in db.pay_lines.find({"worker_id": worker_id}).sort("_id", -1).limit(limit):
        run = db.pay_runs.find_one({"run_id": line["run_id"]})
        if run:
            out.append({"run": _public(run), "line": _public(line)})
    return out
