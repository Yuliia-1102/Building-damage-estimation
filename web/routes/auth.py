"""Sign-in and sign-out (v2.0). Accounts are prepared in advance (web/auth.py); no registration."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from web import audit
from web.auth import COOKIE, SESSION_HOURS, authenticate, make_cookie
from web.db import session_scope
from web.models import User
from web.templating import render

router = APIRouter()


def _safe_next(target: str | None) -> str:
    """Only local paths, so the login form cannot redirect to another site."""
    return target if target and target.startswith("/") and not target.startswith("//") else "/board"


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render("login.html", request, error=None, next=_safe_next(request.query_params.get("next")),
                  username="")


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/board")):
    with session_scope() as s:
        user = authenticate(s, username, password)
        if user is None:
            # Only a name that belongs to an account is stored: a password typed into the name field by
            # mistake must not end up in the audit log (review question on PR #5).
            typed = (username or "").strip()
            known = s.scalar(select(User.id).where(User.username == typed)) is not None
            audit.record(s, None, "login_failed", "user", typed[:40] if known else "(unknown name)",
                         result="denied")
            error = "Неправильне ім'я користувача або пароль."
        else:
            audit.record(s, user, "login", "user", user.id)
            uid = user.id
    if user is None:
        response = render("login.html", request, error=error, next=_safe_next(next), username=username)
        response.status_code = 401
        return response
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(COOKIE, make_cookie(uid), max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout(request: Request):
    with session_scope() as s:
        audit.record(s, request.state.user, "logout", "user", getattr(request.state.user, "id", None))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response
