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

from pymongo import ReturnDocument

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
        unpaid_all = [d for d in worker_days if not d.get("pay_run_id")]
        # Only days the supervisor approved are paid. Absent days count for
        # the summary but pay nothing, so they don't need approving.
        unpaid = [d for d in unpaid_all if d.get("review") == "accepted" or d.get("status") == "A"]
        waiting = [d for d in unpaid_all if d not in unpaid]
        already_paid = len(worker_days) - len(unpaid_all)
        if not unpaid_all and not already_paid:
            continue
        summary = summarise_worker(w, unpaid)
        lines.append({
            "worker_id": w["worker_id"],
            "worker_name": w["name"],
            "trade": w.get("trade", ""),
            "phone": w["phone"],
            "paypal_email": w.get("paypal_email", ""),
            "already_paid_days": already_paid,
            "awaiting_approval": len(waiting),
            "awaiting_dates": sorted(d["date"] for d in waiting),
            "pending_review": 0,
            "needs_photo": 0,
            "dates": sorted(d["date"] for d in unpaid),
            **summary,
            "payout_amount": to_payout_amount(summary["net"], config.PAYOUT_FX_RATE),
        })

    total_net = sum(l["net"] for l in lines)
    _attach_checks(supervisor_id, site_id, lines)
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
    lines = [l for l in draft["lines"] if l["days"] > 0 and l["net"] > 0]
    if worker_ids is not None:
        lines = [l for l in lines if l["worker_id"] in set(worker_ids)]
    if not lines:
        raise AccountError("Nothing to pay: approve the worker's days on the Register first")
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
        "batches": [],
        "batch_seq": 0,
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
            "payout_batch_id": None,
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


_WAITING = ("NOT_SENT", "FAILED")
_IN_FLIGHT = ("SUBMITTING", "PENDING", "ONHOLD")
_OK = ("SUCCESS", "UNCLAIMED")


def _recompute_status(run_id: str) -> None:
    """Run status from its lines: approved → partial → submitted → completed."""
    db = get_db()
    statuses = [l["transaction_status"] for l in db.pay_lines.find({"run_id": run_id, "net": {"$gt": 0}},
                                                                   {"transaction_status": 1})]
    waiting = [s for s in statuses if s in _WAITING]
    sent = [s for s in statuses if s not in _WAITING]
    if not statuses or all(s in _OK for s in statuses):
        status = "completed"
    elif waiting and sent:
        status = "partial"
    elif waiting:
        status = "failed" if "FAILED" in waiting else "approved"
    elif any(s in _IN_FLIGHT for s in statuses):
        status = "submitted"
    else:
        status = "failed"  # all final, but some items were returned or blocked
    update = {"status": status}
    if status == "completed":
        update["completed_at"] = now()
    db.pay_runs.update_one({"run_id": run_id}, {"$set": update})


def pay(supervisor_id: str, run_id: str, worker_ids: Optional[List[str]] = None) -> dict:
    """Send a PayPal Payouts batch for the run's unpaid lines: all of them, or
    only `worker_ids` (one worker's Pay button). A line can only ever be in
    one successful batch."""
    db = get_db()
    run = db.pay_runs.find_one({"supervisor_id": supervisor_id, "run_id": run_id})
    if not run:
        raise AccountError("Pay run not found")

    query = {"run_id": run_id, "net": {"$gt": 0}, "transaction_status": {"$in": list(_WAITING)}}
    if worker_ids is not None:
        query["worker_id"] = {"$in": list(worker_ids)}
    candidates = list(db.pay_lines.find(query))
    if not candidates:
        _recompute_status(run_id)
        raise AccountError("Nothing left to pay" + (" for that worker" if worker_ids else " in this run"))

    # Claim each line first, so a double click can't put it in two batches.
    claimed = []
    for line in candidates:
        r = db.pay_lines.update_one({"_id": line["_id"], "transaction_status": line["transaction_status"]},
                                    {"$set": {"transaction_status": "SUBMITTING", "error": None}})
        if r.modified_count:
            claimed.append(line)
    if not claimed:
        raise AccountError("Already being paid")

    seq = db.pay_runs.find_one_and_update({"_id": run["_id"]}, {"$inc": {"batch_seq": 1}},
                                          return_document=ReturnDocument.AFTER)["batch_seq"]
    sender_batch_id = f"{run_id}-{seq}"  # PayPal rejects a reused id for 30 days
    items = [{
        "receiver": l["paypal_email"],
        "recipient_type": "EMAIL",
        "amount": l["payout_amount"],
        "currency": run["payout_currency"],
        "note": l["note"],
        "sender_item_id": l["sender_item_id"],
    } for l in claimed]
    ids = [l["_id"] for l in claimed]
    batch = {"sender_batch_id": sender_batch_id, "worker_ids": [l["worker_id"] for l in claimed],
             "created_at": now(), "payout_batch_id": None, "batch_status": None, "error": None}
    who = claimed[0]["worker_name"] if len(claimed) == 1 else f"{len(claimed)} workers"

    try:
        result = _client().create_payout(
            sender_batch_id=sender_batch_id,
            items=items,
            email_subject=f"You've been paid: {run['site_name']} ({run['label']})",
            email_message=f"{run['reference']}. Sent with SitePay.",
        )
    except paypal.PayPalError as e:
        db.pay_lines.update_many({"_id": {"$in": ids}}, {"$set": {"transaction_status": "FAILED", "error": str(e)}})
        batch["error"] = str(e)
        db.pay_runs.update_one({"_id": run["_id"]}, {"$push": {"batches": batch}, "$set": {"error": str(e)}})
        _recompute_status(run_id)
        logger.error(f"❌ Payout {sender_batch_id} ({who}) failed: {e} {e.details}")
        raise AccountError(str(e))

    header = result.get("batch_header", {})
    batch.update(payout_batch_id=header.get("payout_batch_id"), batch_status=header.get("batch_status"))
    db.pay_lines.update_many({"_id": {"$in": ids}}, {"$set": {"transaction_status": "PENDING",
                                                               "payout_batch_id": batch["payout_batch_id"]}})
    db.pay_runs.update_one({"_id": run["_id"]}, {
        "$push": {"batches": batch},
        "$set": {"payout_batch_id": batch["payout_batch_id"], "batch_status": batch["batch_status"],
                 "submitted_at": now(), "error": None},
    })
    _recompute_status(run_id)
    logger.info(f"💸 Payout batch {batch['payout_batch_id']} ({who}) submitted for {run_id}")
    return get_run(supervisor_id, run_id)


def refresh(supervisor_id: str, run_id: str) -> dict:
    """Pull status from PayPal for every batch still in progress. Returns the
    run plus `newly_paid` lines whose worker should now get a pay note."""
    db = get_db()
    run = db.pay_runs.find_one({"supervisor_id": supervisor_id, "run_id": run_id})
    if not run:
        raise AccountError("Pay run not found")
    batches = run.get("batches") or []

    newly_paid = []
    for batch in batches:
        if not batch.get("payout_batch_id") or batch.get("batch_status") in paypal.BATCH_FINAL:
            continue
        try:
            result = _client().get_payout(batch["payout_batch_id"])
        except paypal.PayPalError as e:
            raise AccountError(f"Couldn't fetch status from PayPal: {e}")
        for item in result.get("items", []):
            sender_item_id = (item.get("payout_item") or {}).get("sender_item_id")
            line = db.pay_lines.find_one({"run_id": run_id, "sender_item_id": sender_item_id,
                                          "payout_batch_id": batch["payout_batch_id"]})
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
            if status in _OK and not line.get("notified"):
                newly_paid.append({**_public(line), "transaction_status": status})
        batch["batch_status"] = result.get("batch_header", {}).get("batch_status")

    if batches:
        db.pay_runs.update_one({"_id": run["_id"]}, {"$set": {
            "batches": batches, "batch_status": batches[-1].get("batch_status")}})
    _recompute_status(run_id)
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
    _attach_checks(supervisor_id, run["site_id"], run["lines"])
    return run


def _attach_checks(supervisor_id: str, site_id: str, lines: List[dict]) -> None:
    """Give each pay line the AI check for its days, so the supervisor sees
    the verdict next to the Pay button."""
    import checks
    dates = sorted({d for l in lines for d in l.get("dates", [])})
    if not dates:
        return
    by_day = checks.checks_for(supervisor_id, site_id, dates)
    for line in lines:
        day_checks = [{**by_day[(line["worker_id"], d)], "date": d}
                      for d in line.get("dates", []) if (line["worker_id"], d) in by_day]
        line["check"] = checks.worker_period(day_checks)
        latest = next((c for c in reversed(day_checks) if c.get("attendance") or c.get("work")), None)
        line["check"]["latest"] = ({"date": latest["date"], "attendance": latest.get("attendance", ""),
                                    "work": latest.get("work", ""), "state": latest["state"]}
                                   if latest else None)


def list_runs(supervisor_id: str) -> List[dict]:
    db = get_db()
    runs = [_public(r) for r in db.pay_runs.find({"supervisor_id": supervisor_id}).sort("approved_at", -1)]
    for r in runs:
        r["lines"] = [_public(l) for l in db.pay_lines.find({"run_id": r["run_id"]}).sort("worker_name", 1)]
    return runs


def runs_for_worker(worker_id: str, limit: int = 3) -> List[dict]:
    db = get_db()
    out = []
    for line in db.pay_lines.find({"worker_id": worker_id}).sort("_id", -1).limit(limit):
        run = db.pay_runs.find_one({"run_id": line["run_id"]})
        if run:
            out.append({"run": _public(run), "line": _public(line)})
    return out
