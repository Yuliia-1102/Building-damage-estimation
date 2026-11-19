"""v2.0: sign-in, permissions checked on the server, and the audit log of every action."""
import pytest
from sqlalchemy import select

from web import service
from web.models import AuditEvent, Status


def _events(db, **where):
    with db() as s:
        stmt = select(AuditEvent)
        for k, v in where.items():
            stmt = stmt.where(getattr(AuditEvent, k) == v)
        rows = s.scalars(stmt.order_by(AuditEvent.id)).all()
        s.expunge_all()
        return rows


def _processed(create, pump, db, case="photo_single") -> int:
    aid = create(case, "права")
    pump()
    with db() as s:
        assert service.get(s, aid).status == Status.PROCESSED
    return aid


# ---------- sign-in ----------

def test_pages_need_sign_in_but_health_does_not(client):
    from fastapi.testclient import TestClient
    from web.server import app
    anonymous = TestClient(app)
    r = anonymous.get("/board", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert anonymous.get("/healthz").status_code == 200
    assert anonymous.post("/applications/1/approve", follow_redirects=False).status_code == 303   # to login


def test_wrong_password_is_refused_and_recorded(client, db):
    from fastapi.testclient import TestClient
    from web.server import app
    r = TestClient(app).post("/login", data={"username": "operator1", "password": "wrong"})
    assert r.status_code == 401 and "Неправильне" in r.text
    assert _events(db, action="login_failed")[-1].result == "denied"


def test_deactivated_user_cannot_sign_in(admin_client, db):
    from web.models import User
    with db() as s:
        uid = s.scalar(select(User.id).where(User.username == "operator2"))
    admin_client.post(f"/admin/users/{uid}/active", data={"active": "0"})
    from tests.web.conftest import login_as
    with pytest.raises(AssertionError):
        login_as("operator2")


# ---------- permissions ----------

@pytest.mark.parametrize("action,data", [
    ("approve", {}),
    ("decline", {"reason": "чужа"}),
    ("reevaluate", {"floors": "9"}),
    ("assign", {"project_id": ""}),
])
def test_other_operator_is_refused(client, other_client, create, pump, db, action, data):
    aid = _processed(create, pump, db)
    r = other_client.post(f"/applications/{aid}/{action}", data=data, follow_redirects=False)
    assert r.status_code == 403
    with db() as s:
        assert service.get(s, aid).status == Status.PROCESSED
    denied = _events(db, object_id=str(aid), result="denied")
    assert denied and denied[-1].username == "operator2"


def test_owner_and_admin_may_decide(client, admin_client, create, pump, db):
    own = _processed(create, pump, db)
    assert client.post(f"/applications/{own}/decline", data={"reason": "потрібні фото"},
                       follow_redirects=False).status_code == 303
    other = _processed(create, pump, db, case="download10")
    assert admin_client.post(f"/applications/{other}/approve", follow_redirects=False).status_code == 303
    with db() as s:
        assert service.get(s, other).status == Status.APPROVED
        last = service.get(s, other).history[-1]
        assert last.user.username == "admin"


def test_operator_cannot_change_prices_or_open_admin(client, db):
    assert client.post("/materials/price", data={"material_id": 1, "value": "1"}).status_code == 403
    assert client.post("/materials/labour", data={"work_code": "x", "value": "1"}).status_code == 403
    assert client.get("/admin/audit").status_code == 403
    assert client.post("/admin/users", data={"username": "x", "display_name": "x", "role": "admin",
                                             "password": "12345678"}).status_code == 403
    assert {e.action for e in _events(db, result="denied")} >= {"price_changed", "labour_rate_changed"}


def test_only_mine_filter(client, other_client, create, pump, db):
    mine = create("photo_single", "моя")
    from tests.web.conftest import pack_path
    path = pack_path("inputs", "download10")
    import os
    f = os.path.join(path, sorted(os.listdir(path))[0])
    with open(f, "rb") as fh:
        other_client.post("/applications", data={"title": "чужа", "comment": "", "project_id": ""},
                          files=[("files", (os.path.basename(f), fh.read(), "application/octet-stream"))])
    page = client.get("/board?mine=1").text
    assert f"№{mine} · моя" in page and "чужа" not in page
    assert "чужа" in client.get("/board").text


# ---------- audit log ----------

def test_full_path_is_audited(client, admin_client, create, pump, db):
    """End to end through the interface: create -> processing -> see it -> decline own; every step is logged."""
    client.post("/projects", data={"name": "Аудит", "description": ""})
    aid = create("photo_single", "аудит")
    pump()
    assert client.get(f"/applications/{aid}").status_code == 200
    client.post(f"/applications/{aid}/decline", data={"reason": "потрібні фото з інших сторін"})
    actions = [(e.username, e.action) for e in _events(db)]
    for expected in [("operator1", "login"), ("operator1", "project_created"),
                     ("operator1", "application_created"), ("operator1", "file_uploaded"),
                     ("system", "processing_started"), ("system", "processing_finished"),
                     ("operator1", "application_declined")]:
        assert expected in actions, expected
    created = _events(db, action="application_created", object_id=str(aid))[0]
    assert created.request_id and created.at is not None
    page = admin_client.get(f"/admin/audit?object_id={aid}").text
    assert "відхилено заявку" in page and "operator1" in page


def test_audit_log_has_no_edit_or_delete_routes(client):
    from web.server import app
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/admin/audit"):
            assert getattr(route, "methods", {"GET"}) <= {"GET", "HEAD"}, path


def test_admin_pages_open(admin_client):
    assert admin_client.get("/admin/users").status_code == 200
    r = admin_client.post("/admin/users", data={"username": "operator3", "display_name": "Оператор 3",
                                                "role": "operator", "password": "password3"})
    assert "Користувача створено" in r.text and "operator3" in r.text
    assert admin_client.get("/admin/audit?action=user_created").text.count("створено користувача") >= 1
    assert "Нова ціна матеріалу" in admin_client.get("/materials").text
