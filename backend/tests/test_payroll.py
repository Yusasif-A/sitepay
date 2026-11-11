import pytest

from payroll import default_ot_rate, summarise_worker, to_payout_amount


def test_doc_example_register():
    # Section 4 of the product doc
    musa = summarise_worker({"daily_rate": 12000, "ot_rate": 2250}, [{"status": "OT", "ot_hours": 2}])
    assert musa["gross"] == 12000 + 2 * 2250
    chinedu = summarise_worker({"daily_rate": 6500, "ot_rate": 0}, [{"status": "H", "advance": 1000}])
    assert chinedu["gross"] == 3250 and chinedu["net"] == 2250
    ibrahim = summarise_worker({"daily_rate": 15000, "ot_rate": 0}, [{"status": "A"}])
    assert ibrahim["net"] == 0


def test_period_formula_and_counts():
    w = {"daily_rate": 9000, "ot_rate": 1500}
    days = [{"status": "P"}] * 4 + [{"status": "H"}, {"status": "A", "ot_hours": 5}, {"status": "OT", "ot_hours": 2}]
    s = summarise_worker(w, days)
    # OT hours on an Absent day must not pay
    assert s["gross"] == 4 * 9000 + 4500 + 9000 + 2 * 1500
    assert s["counts"]["P"] == 4 and s["counts"]["H"] == 1 and s["counts"]["A"] == 1
    assert s["ot_hours"] == 2


def test_frozen_rates_on_day_win():
    s = summarise_worker({"daily_rate": 20000, "ot_rate": 0}, [{"status": "P", "daily_rate": 10000}])
    assert s["gross"] == 10000


def test_advance_exceeding_gross_never_negative():
    s = summarise_worker({"daily_rate": 5000}, [{"status": "H", "advance": 4000}])
    assert s["net"] == 0 and s["carry_over_debt"] == 1500


def test_rounding_once_per_period():
    s = summarise_worker({"daily_rate": 6501}, [{"status": "H"}] * 2)
    assert s["gross"] == 6501


def test_payout_amount_format():
    assert to_payout_amount(15000, 1500) == "10.00"
    assert to_payout_amount(2250, 1500) == "1.50"
    assert to_payout_amount(1, 1500) == "0.00"
    with pytest.raises(ValueError):
        to_payout_amount(100, 0)


def test_default_ot_rate():
    assert default_ot_rate(12000) == 2250
