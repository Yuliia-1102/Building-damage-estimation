"""State model of an application: allowed and forbidden transitions, one decision only, concurrent decisions."""
import threading

import pytest
from sqlalchemy import func, select

from web import service
from web.models import Application, Status, StatusChange


# ---------- unit: the transition table ----------

@pytest.mark.parametrize("frm,to", [
    (None, Status.CREATED),
    (Status.CREATED, Status.PROCESSING),
    (Status.PROCESSING, Status.PROCESSED),
    (Status.PROCESSING, Status.FAILED),
    (Status.PROCESSED, Status.APPROVED),
    (Status.PROCESSED, Status.DECLINED),
    (Status.APPROVED, Status.PROCESSED),     # reopened
    (Status.FAILED, Status.CREATED),         # retry
])
def test_allowed_transitions(frm, to):
    assert Status.allowed(frm, to)


@pytest.mark.parametrize("frm,to", [
    (None, Status.PROCESSED),                # a new application starts in Created
    (Status.CREATED, Status.APPROVED),       # nothing to approve before processing
    (Status.PROCESSING, Status.APPROVED),
    (Status.APPROVED, Status.APPROVED),      # a second decision
    (Status.APPROVED, Status.DECLINED),      # changing a decision without reopening
    (Status.DECLINED, Status.APPROVED),
    (Status.FAILED, Status.APPROVED),
    (Status.FAILED, Status.PROCESSED),
])
def test_forbidden_transitions(frm, to):
    assert not Status.allowed(frm, to)


def test_transition_raises_on_forbidden_change(client, db):
    with db() as s:
        app = Application(title="t", status=Status.CREATED)
        s.add(app)
        s.flush()
        with pytest.raises(service.InvalidTransition):
            service.transition(s, app, Status.APPROVED)


# ---------- integration: one decision, also under concurrency ----------

def _processed(create, pump, db) -> int:
    aid = create("photo_single", "рішення")
    pump()
    with db() as s:
        assert service.get(s, aid).status == Status.PROCESSED
    return aid


def _decisions(db, aid: int) -> int:
    with db() as s:
        return s.scalar(select(func.count()).select_from(StatusChange).where(
            StatusChange.application_id == aid,
            StatusChange.to_status.in_([Status.APPROVED, Status.DECLINED])))


def test_second_decision_is_a_conflict(client, create, pump, db):
    aid = _processed(create, pump, db)
    assert client.post(f"/applications/{aid}/approve", follow_redirects=False).status_code == 303
    r = client.post(f"/applications/{aid}/decline", data={"reason": "пізно"}, follow_redirects=False)
    assert r.status_code == 409
    with db() as s:
        assert service.get(s, aid).status == Status.APPROVED
    assert _decisions(db, aid) == 1


def test_two_concurrent_decisions_give_one_result(client, create, pump, db):
    aid = _processed(create, pump, db)
    start = threading.Barrier(2)
    outcome: list[str] = []

    def decide(to_status):
        start.wait()
        try:
            with db() as s:
                service.decide(s, aid, to_status, comment="паралельно")
            outcome.append("ok")
        except service.Conflict:
            outcome.append("conflict")

    threads = [threading.Thread(target=decide, args=(st,)) for st in (Status.APPROVED, Status.DECLINED)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcome) == ["conflict", "ok"]
    assert _decisions(db, aid) == 1
    with db() as s:
        assert service.get(s, aid).status in (Status.APPROVED, Status.DECLINED)


def test_validation_and_not_found_differ_from_failure(client, create, pump, db):
    aid = _processed(create, pump, db)
    assert client.post(f"/applications/{aid}/decline", data={"reason": " "}).status_code == 400
    assert client.post("/applications/99999/approve").status_code == 404


def test_error_page_escapes_text():
    from web.routes.applications import error_page
    body = error_page(400, "<script>alert(1)</script>", back='/x"><b>').body.decode()
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert '"><b>' not in body
