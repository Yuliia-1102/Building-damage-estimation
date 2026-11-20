"""/healthz: healthy when the queue moves, 503 when an application waits longer than the limit."""
from datetime import datetime, timedelta

from web.models import Application, Status
from web.server import STUCK_QUEUE_MINUTES


def _add_queued(db, minutes_ago: int) -> None:
    with db() as s:
        s.add(Application(title="health", status=Status.CREATED,
                          queued_at=datetime.now() - timedelta(minutes=minutes_ago)))


def test_health_ok_on_fresh_queue(client, db):
    _add_queued(db, minutes_ago=1)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "db": "ok", "stuck_in_queue": 0}


def test_health_fails_when_queue_is_stuck(client, db):
    _add_queued(db, minutes_ago=STUCK_QUEUE_MINUTES + 1)
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json()["ok"] is False and r.json()["stuck_in_queue"] == 1


def test_health_hides_error_details(client, monkeypatch):
    import web.server

    def broken(_sql):                     # the database check inside /healthz fails
        raise RuntimeError("/secret/path/web.db is locked")
    monkeypatch.setattr(web.server, "text", broken)
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json() == {"ok": False, "db": "error"}
