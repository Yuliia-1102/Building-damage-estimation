"""Sign-in, sessions and permissions (v2.0).

- Passwords are stored as PBKDF2-SHA256 hashes with a random salt (standard library, no extra dependency).
- The session is a signed cookie with the user id (itsdangerous); it expires after SESSION_HOURS.
- The signing secret comes from DAMAGE_WEB_SECRET, or is generated once into <data>/secret.key (never in git).
- Permissions are checked on the server (can_change / require_admin); hiding a button is only a convenience.

Prepared training accounts (no registration, no password recovery - out of scope by the lab conditions) are
created by ensure_demo_users() on the first start: admin, operator1, operator2. Their password is
DAMAGE_DEMO_PASSWORD, or "demo2026" when it is not set (training data only; README says so).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from web import config
from web.models import LEGACY_USERNAME, Application, Role, User

COOKIE = "session"
SESSION_HOURS = 12
PBKDF2_ROUNDS = 200_000

DEMO_USERS = [
    ("admin", "Адміністратор", Role.ADMIN),
    ("operator1", "Оператор 1", Role.OPERATOR),
    ("operator2", "Оператор 2", Role.OPERATOR),
]


@dataclass(frozen=True)
class CurrentUser:
    """The signed-in user as the routes see it (a plain value, safe to use after the session closes)."""
    id: int
    username: str
    display_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN


# ---------- passwords ----------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
    except ValueError:
        return False
    test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
    return hmac.compare_digest(test, digest)


# ---------- session cookie ----------

def _secret() -> str:
    env = os.environ.get("DAMAGE_WEB_SECRET")
    if env:
        return env
    path = config.DATA_DIR / "secret.key"
    if not path.exists():
        config.ensure_dirs()
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="session")


def make_cookie(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def user_from_cookie(session: Session, value: str | None) -> CurrentUser | None:
    if not value:
        return None
    try:
        data = _serializer().loads(value, max_age=SESSION_HOURS * 3600)
    except (BadSignature, SignatureExpired):
        return None
    user = session.get(User, data.get("uid"))
    if user is None or not user.active:
        return None
    return CurrentUser(user.id, user.username, user.display_name, user.role)


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == (username or "").strip()))
    if user is None or not user.active or not user.password_hash:
        return None
    return user if verify_password(password or "", user.password_hash) else None


# ---------- permissions ----------

def can_change(user: CurrentUser, app: Application) -> bool:
    """Only the owner of an application or an administrator may act on it (approve, decline, retry, ...)."""
    return user.is_admin or app.owner_id == user.id


# ---------- prepared accounts ----------

def ensure_demo_users(session: Session) -> None:
    """Create the training accounts and the legacy owner if they do not exist yet (idempotent)."""
    password = os.environ.get("DAMAGE_DEMO_PASSWORD", "demo2026")
    have = set(session.scalars(select(User.username)).all())
    for username, name, role in DEMO_USERS:
        if username not in have:
            session.add(User(username=username, display_name=name, role=role,
                             password_hash=hash_password(password)))
    if LEGACY_USERNAME not in have:
        session.add(User(username=LEGACY_USERNAME, display_name="До v2.0 (автор невідомий)",
                         role=Role.OPERATOR, password_hash="", active=False))
    session.flush()
