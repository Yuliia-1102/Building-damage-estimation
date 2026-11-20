"""Audit log (v2.0): every user action is one row in audit_event and one line in the log file.

record() is the only writer. Rows are never edited or deleted (no route or function does it), so the table
answers "who did what, to which object, when, and was it allowed".

Actions (the `action` column):
  login, login_failed, logout,
  application_created, file_uploaded, application_approved, application_declined, application_reopened,
  application_retried, parameters_corrected, duplicate_resolved, project_assigned,
  project_created, price_changed, material_added, labour_rate_changed,
  user_created, user_deactivated, user_activated,
  processing_started, processing_finished, processing_failed   (by the worker, user "system")
Results: ok, denied (no permission), error.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from web.models import AuditEvent

log = logging.getLogger("web.audit")

# Set by the request middleware (web/server.py) so every record of one request shares an id.
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

ACTIONS_UA = {
    "login": "вхід", "login_failed": "невдалий вхід", "logout": "вихід",
    "application_created": "створено заявку", "file_uploaded": "завантажено файл",
    "application_approved": "затверджено заявку", "application_declined": "відхилено заявку",
    "application_reopened": "повернено на розгляд", "application_retried": "повторна обробка",
    "parameters_corrected": "змінено параметри будівлі", "duplicate_resolved": "вирішено дублікат",
    "project_assigned": "заявку додано до проєкту", "project_created": "створено проєкт",
    "price_changed": "змінено ціну матеріалу", "material_added": "додано матеріал",
    "labour_rate_changed": "змінено розцінку", "user_created": "створено користувача",
    "user_deactivated": "деактивовано користувача", "user_activated": "активовано користувача",
    "processing_started": "почато обробку", "processing_finished": "оброблено",
    "processing_failed": "збій обробки",
}
RESULTS_UA = {"ok": "успішно", "denied": "відмовлено", "error": "помилка"}


def record(session: Session, user, action: str, object_type: str | None = None, object_id=None,
           result: str = "ok", details: str | None = None) -> AuditEvent:
    """Add one audit row. `user` is a CurrentUser / User or None for the system (the worker)."""
    event = AuditEvent(
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None) or "system",
        action=action,
        object_type=object_type,
        object_id=None if object_id is None else str(object_id),
        result=result,
        details=details,
        request_id=request_id.get(),
    )
    session.add(event)
    log.info("audit rid=%s user=%s action=%s object=%s:%s result=%s %s", event.request_id or "-",
             event.username, action, object_type or "-", event.object_id or "-", result, details or "")
    return event


def query(session: Session, *, username: str | None = None, action: str | None = None,
          object_type: str | None = None, object_id: str | None = None, result: str | None = None,
          date_from=None, date_to=None, limit: int = 500) -> list[AuditEvent]:
    stmt = select(AuditEvent)
    if username:
        stmt = stmt.where(AuditEvent.username == username)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if object_type:
        stmt = stmt.where(AuditEvent.object_type == object_type)
    if object_id:
        stmt = stmt.where(AuditEvent.object_id == str(object_id))
    if result:
        stmt = stmt.where(AuditEvent.result == result)
    if date_from:
        stmt = stmt.where(AuditEvent.at >= date_from)
    if date_to:
        stmt = stmt.where(AuditEvent.at <= date_to)
    return list(session.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit)).all())
