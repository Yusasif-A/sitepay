"""The AI check verdict the supervisor reads before accepting or paying."""

import checks


def _rec(**kw):
    base = {"date": "2026-11-11", "status": "P", "source": "whatsapp",
            "check_in_location": {"lat": 6.4474, "lon": 3.4723}, "check_in_photo": "EV-CI"}
    base.update(kw)
    return base


def _ai(**kw):
    base = {"ok": True, "is_work_related": True, "on_site": True, "person_visible": True,
            "work_status": "in_progress", "finding": "", "progress": "", "summary": "",
            "visible_timestamp": "", "timestamp_date": None}
    base.update(kw)
    return base


def _photo(eid, purpose, ai, flags=()):
    return {"evidence_id": eid, "kind": "photo", "purpose": purpose, "ai": ai, "flags": list(flags)}


def test_verified_day_gives_attendance_and_work_findings():
    evs = [
        _photo("EV-CI", "check_in", _ai(finding="Worker present on site: mason in hi-vis at a block building.",
                                        visible_timestamp="11 NOV 2026 07:14 AM", timestamp_date="2026-11-11",
                                        work_status="not_visible")),
        _photo("EV-W", "work", _ai(person_visible=False, finding="Blockwork in progress: wall about 8 courses.")),
    ]
    c = checks.day_check(_rec(), evs)
    assert c["state"] == "verified" and not c["issues"]
    assert c["attendance"].startswith("Worker present on site")
    assert c["work"].startswith("Blockwork in progress")
    labels = [i["label"] for i in c["items"]]
    assert "Location shared" in labels and "Photo date stamp matches the day" in labels


def test_no_location_no_photo_is_no_proof():
    c = checks.day_check(_rec(check_in_location=None, check_in_photo=None), [])
    assert c["state"] == "no_proof"


def test_dashboard_logged_day_is_manual():
    c = checks.day_check(_rec(check_in_location=None, check_in_photo=None, source="dashboard"), [])
    assert c["state"] == "manual"


def test_issues_are_listed():
    evs = [
        _photo("EV-CI", "check_in", _ai(person_visible=False, timestamp_date="2026-11-09",
                                        visible_timestamp="09 NOV 2026")),
        _photo("EV-W", "work", _ai(on_site=False, is_work_related=False, work_status="not_visible"),
               flags=["duplicate_other_day"]),
    ]
    c = checks.day_check(_rec(), evs)
    assert c["state"] == "issues"
    assert "Worker visible in check-in photo" in c["issues"]
    assert "Photo date stamp matches the day" in c["issues"]
    assert "Work visible in work photo" in c["issues"]
    assert "Fresh photos (not reused from another day)" in c["issues"]


def test_missing_work_photo_is_an_issue_and_pending_ai_waits():
    c = checks.day_check(_rec(), [_photo("EV-CI", "check_in", _ai())])
    assert c["state"] == "issues" and "Work photo sent" in c["issues"]
    c = checks.day_check(_rec(), [_photo("EV-CI", "check_in", None), _photo("EV-W", "work", None)])
    assert c["state"] == "pending"


def test_absent_day():
    assert checks.day_check(_rec(status="A"), [])["state"] == "absent"
