"""Administration (v2.0): users and the audit log. Every route here is for administrators only."""
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from web import audit
from web.auth import hash_password
from web.db import session_scope
from web.models import LEGACY_USERNAME, UA_ROLE, Role, User
from web.templating import render

router = APIRouter(prefix="/admin")


def _guard(request: Request, action: str) -> HTMLResponse | None:
    user = request.state.user
    if user.is_admin:
        return None
    with session_scope() as s:
        audit.record(s, user, action, "admin", request.url.path, result="denied", details="not an administrator")
    return HTMLResponse('<p>Розділ лише для адміністратора.</p><p><a href="/board">Назад</a></p>', status_code=403)


# ---------- audit log ----------

@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    if (denied := _guard(request, "admin_opened")):
        return denied
    q = request.query_params

    def day(key, end=False):
        try:
            d = datetime.strptime(q.get(key, ""), "%Y-%m-%d")
            return d.replace(hour=23, minute=59, second=59) if end else d
        except ValueError:
            return None

    with session_scope() as s:
        events = audit.query(s, username=q.get("username") or None, action=q.get("action") or None,
                             object_type=q.get("object_type") or None, object_id=q.get("object_id") or None,
                             result=q.get("result") or None, date_from=day("date_from"),
                             date_to=day("date_to", end=True))
        usernames = sorted(set(s.scalars(select(User.username)).all()) | {"system"})
        s.expunge_all()
    return render("admin_audit.html", request, events=events, raw=dict(q), usernames=usernames,
                  actions=audit.ACTIONS_UA, results=audit.RESULTS_UA)


# ---------- users ----------

@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    if (denied := _guard(request, "admin_opened")):
        return denied
    with session_scope() as s:
        users = list(s.scalars(select(User).where(User.username != LEGACY_USERNAME).order_by(User.id)).all())
        s.expunge_all()
    q = request.query_params
    return render("admin_users.html", request, users=users, roles=UA_ROLE, msg=q.get("msg"), err=q.get("err"))


@router.post("/users")
def create_user(request: Request, username: str = Form(...), display_name: str = Form(...),
                role: str = Form(Role.OPERATOR), password: str = Form(...)):
    if (denied := _guard(request, "user_created")):
        return denied
    username = username.strip()
    if role not in Role.ALL or not username or len(password) < 8:
        return RedirectResponse("/admin/users?err=Перевірте+дані:+роль,+ім'я,+пароль+щонайменше+8+символів",
                                status_code=303)
    with session_scope() as s:
        if s.scalar(select(User).where(User.username == username)):
            return RedirectResponse("/admin/users?err=Такий+користувач+уже+є", status_code=303)
        user = User(username=username, display_name=display_name.strip() or username, role=role,
                    password_hash=hash_password(password))
        s.add(user)
        s.flush()
        audit.record(s, request.state.user, "user_created", "user", user.id, details=f"{username} role={role}")
    return RedirectResponse("/admin/users?msg=Користувача+створено", status_code=303)


@router.post("/users/{user_id}/active")
def set_active(request: Request, user_id: int, active: str = Form(...)):
    action = "user_activated" if active == "1" else "user_deactivated"
    if (denied := _guard(request, action)):
        return denied
    with session_scope() as s:
        user = s.get(User, user_id)
        if user is None or user.username == LEGACY_USERNAME:
            return RedirectResponse("/admin/users?err=Користувача+не+знайдено", status_code=303)
        if user.id == request.state.user.id:
            return RedirectResponse("/admin/users?err=Не+можна+деактивувати+себе", status_code=303)
        user.active = active == "1"
        audit.record(s, request.state.user, action, "user", user.id, details=user.username)
    return RedirectResponse("/admin/users?msg=Збережено", status_code=303)
