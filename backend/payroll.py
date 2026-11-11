"""
Hajri-style wage math. Pure functions only, with no database and no I/O, so
the numbers a supervisor approves are easy to test and to reason about.

Status codes (see the product doc, section 4):

    P   Present (full day)      1 × daily rate
    A   Absent                  0
    H   Half day                0.5 × daily rate
    OT  Present + overtime      1 × daily rate (+ OT hours × OT rate)
    L   Paid leave              1 × daily rate (as agreed with the contractor)

Overtime hours and advances are separate fields on every day, not statuses:
OT hours pay at the worker's OT rate on any worked day (P, H or OT), and an
advance is deducted from the period total whatever the day's status.

All amounts are whole units of the wage currency (e.g. naira). Rounding
happens once per worker per period, never per day, so a run of half days
can't drift by a unit each.
"""

from typing import Dict, Iterable, List

STATUSES = ("P", "A", "H", "OT", "L")
WORKED = ("P", "H", "OT")  # statuses on which overtime hours count

STATUS_LABELS = {
    "P": "Present",
    "A": "Absent",
    "H": "Half day",
    "OT": "Overtime",
    "L": "Paid leave",
}

_DAY_FACTOR = {"P": 1.0, "A": 0.0, "H": 0.5, "OT": 1.0, "L": 1.0}

MAX_OT_HOURS = 12


def default_ot_rate(daily_rate: int) -> int:
    """1.5× the hourly rate of an 8-hour day, which is what a supervisor gets
    if they don't set an OT rate themselves."""
    return int(round(daily_rate / 8 * 1.5))


def day_gross(status: str, daily_rate: float, ot_hours: float, ot_rate: float) -> float:
    """Unrounded gross for one day."""
    if status not in _DAY_FACTOR:
        raise ValueError(f"Unknown status {status!r}")
    gross = _DAY_FACTOR[status] * daily_rate
    if status in WORKED:
        gross += max(0.0, float(ot_hours or 0)) * ot_rate
    return gross


def summarise_worker(worker: dict, days: Iterable[dict]) -> dict:
    """Period summary for one worker.

    `worker` needs daily_rate and ot_rate. Each day needs status, and
    optionally ot_hours and advance. Uses the rates stored on the day when
    present (they are frozen onto the record when the day is logged, so a
    later raise doesn't rewrite last week's pay), else the worker's rates.
    """
    counts: Dict[str, int] = {s: 0 for s in STATUSES}
    ot_hours_total = 0.0
    gross = 0.0
    advances = 0
    day_count = 0

    for day in days:
        status = day.get("status", "A")
        rate = day.get("daily_rate", worker.get("daily_rate", 0)) or 0
        ot_rate = day.get("ot_rate", worker.get("ot_rate", 0)) or 0
        ot = float(day.get("ot_hours") or 0) if status in WORKED else 0.0
        counts[status] = counts.get(status, 0) + 1
        ot_hours_total += ot
        gross += day_gross(status, rate, ot, ot_rate)
        advances += int(day.get("advance") or 0)
        day_count += 1

    gross_rounded = int(round(gross))
    return {
        "days": day_count,
        "counts": counts,
        "ot_hours": round(ot_hours_total, 2),
        "gross": gross_rounded,
        "advances": advances,
        # Advances larger than earnings carry over as debt; the period itself
        # never pays out a negative amount.
        "net": max(0, gross_rounded - advances),
        "carry_over_debt": max(0, advances - gross_rounded),
    }


def to_payout_amount(net_local: int, fx_rate: float) -> str:
    """Convert a local-currency net into the payout currency as PayPal's
    two-decimal string ("12.34"). fx_rate = local units per payout unit."""
    if fx_rate <= 0:
        raise ValueError("fx_rate must be positive")
    cents = int(round(net_local * 100 / fx_rate))
    return f"{cents // 100}.{cents % 100:02d}"


def counts_phrase(counts: Dict[str, int]) -> str:
    """'Present 4 days, Half 1 day' for a pay note."""
    parts: List[str] = []
    for code, label in (("P", "Present"), ("OT", "Overtime"), ("H", "Half"), ("L", "Leave")):
        n = counts.get(code, 0)
        if n:
            parts.append(f"{label} {n} day{'s' if n != 1 else ''}")
    return ", ".join(parts) or "no paid days"
