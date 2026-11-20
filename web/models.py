"""Database tables for the web system (docs/web_system.md, section 6).

application        one operator request: files, status, the engine result, a copy of summary for fast filtering
application_file   one uploaded file of an application, with its sha256 (duplicate control, section 7)
project            a named group of applications (a street, a community)
status_change      the history of status transitions, one row per change (v2.0: with the user who made it)
app_user           (v2.0) a person who signs in: operator or administrator
audit_event        (v2.0) every user action: who, what, which object, when, result
schema_version     (v2.0) which migration the database is at (web/migrate.py)
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from web.db import Base


class Status:
    """Allowed application statuses and the transitions between them (section 6)."""
    CREATED = "Created"
    PROCESSING = "Processing"
    PROCESSED = "Processed"
    APPROVED = "Approved"
    DECLINED = "Declined"
    FAILED = "Failed"

    ALL = [CREATED, PROCESSING, PROCESSED, APPROVED, DECLINED, FAILED]
    # Shown on the board in this order (left to right).
    BOARD = [CREATED, PROCESSING, PROCESSED, APPROVED, DECLINED, FAILED]

    # The only allowed transitions (the state model in docs/v2/state_model.md). A status may also "move" to
    # itself only where listed: Created -> Created is a re-queue (duplicate merged into it, operator continued).
    TRANSITIONS: dict[str, frozenset[str]] = {
        CREATED: frozenset({PROCESSING, DECLINED, CREATED}),     # picked by the worker / rejected duplicate
        PROCESSING: frozenset({PROCESSED, FAILED, CREATED}),    # finished / failed / worker restarted
        PROCESSED: frozenset({APPROVED, DECLINED, CREATED}),    # operator decision / merged files re-process
        APPROVED: frozenset({PROCESSED, CREATED}),              # reopened / merged files re-process
        DECLINED: frozenset({PROCESSED, CREATED}),
        FAILED: frozenset({CREATED, DECLINED}),                 # retry / declined
    }

    @classmethod
    def allowed(cls, frm: str | None, to: str) -> bool:
        """True if an application may go from `frm` to `to`; None is a new application (only to Created)."""
        if frm is None:
            return to == cls.CREATED
        return to in cls.TRANSITIONS.get(frm, frozenset())


UA_STATUS = {
    Status.CREATED: "Створено",
    Status.PROCESSING: "Обробляється",
    Status.PROCESSED: "Оброблено",
    Status.APPROVED: "Затверджено",
    Status.DECLINED: "Відхилено",
    Status.FAILED: "Збій",
}


class Role:
    OPERATOR = "operator"
    ADMIN = "admin"
    ALL = [OPERATOR, ADMIN]


UA_ROLE = {Role.OPERATOR: "оператор", Role.ADMIN: "адміністратор"}

# The owner given to applications that existed before v2.0 (web/migrate.py). Cannot sign in.
LEGACY_USERNAME = "legacy"


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default=Role.OPERATOR)
    password_hash: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def role_ua(self) -> str:
        return UA_ROLE.get(self.role, self.role)


class AuditEvent(Base):
    """One user action. Rows are only ever added: there is no code path that edits or deletes them."""
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), default=None, index=True)
    username: Mapped[str] = mapped_column(String(50), default="system")   # kept even if the user is renamed
    action: Mapped[str] = mapped_column(String(40), index=True)
    object_type: Mapped[str | None] = mapped_column(String(30), default=None)
    object_id: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    result: Mapped[str] = mapped_column(String(10), default="ok")          # ok / denied / error
    details: Mapped[str | None] = mapped_column(Text, default=None)
    request_id: Mapped[str | None] = mapped_column(String(16), default=None, index=True)


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), default=None)

    created_by: Mapped[User | None] = relationship()

    applications: Mapped[list["Application"]] = relationship(back_populates="project")


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(20), default=Status.CREATED, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), default=None, index=True)
    mode: Mapped[str | None] = mapped_column(String(10), default=None)   # photo / photos / video
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), default=None, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_text: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    result_dir: Mapped[str | None] = mapped_column(String(400), default=None)

    # Duplicate control (section 7).
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("application.id"), default=None)
    merged: Mapped[bool] = mapped_column(default=False)   # files moved into another application; excluded from dup search

    # Operator decision (section 6).
    decision_comment: Mapped[str | None] = mapped_column(Text, default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    # Copy of result.json summary, for the board, filters and statistics (written by the worker on success).
    has_assessment: Mapped[bool | None] = mapped_column(default=None)
    damage_category: Mapped[str | None] = mapped_column(String(4), default=None, index=True)
    condition_category: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    escalation: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    cost_low: Mapped[int | None] = mapped_column(Integer, default=None)
    cost_high: Mapped[int | None] = mapped_column(Integer, default=None)
    cost_total: Mapped[int | None] = mapped_column(Integer, default=None)
    simulated: Mapped[bool] = mapped_column(default=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)

    project: Mapped[Project | None] = relationship(back_populates="applications")
    owner: Mapped[User | None] = relationship()
    files: Mapped[list["ApplicationFile"]] = relationship(
        back_populates="application", cascade="all, delete-orphan")
    history: Mapped[list["StatusChange"]] = relationship(
        back_populates="application", cascade="all, delete-orphan",
        order_by="StatusChange.at")

    # --- small helpers used by templates and logic ---

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of_id is not None and not self.merged

    @property
    def can_decide(self) -> bool:
        return self.status == Status.PROCESSED

    @property
    def can_retry(self) -> bool:
        return self.status == Status.FAILED

    @property
    def status_ua(self) -> str:
        return UA_STATUS.get(self.status, self.status)

    def apply_summary(self, summary: dict, revision: int, simulated: bool) -> None:
        """Copy the fields the board and statistics need out of result.json['summary']."""
        self.has_assessment = bool(summary.get("has_assessment"))
        self.damage_category = summary.get("damage_category")
        self.condition_category = summary.get("condition_category")
        self.escalation = summary.get("escalation")
        self.confidence = summary.get("confidence")
        self.cost_low = summary.get("cost_low")
        self.cost_high = summary.get("cost_high")
        self.cost_total = summary.get("cost_total")
        self.simulated = bool(simulated)
        self.revision = revision


class ApplicationFile(Base):
    __tablename__ = "application_file"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(400))
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    application: Mapped[Application] = relationship(back_populates="files")


class StatusChange(Base):
    __tablename__ = "status_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), default=None)
    to_status: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), default=None)

    application: Mapped[Application] = relationship(back_populates="history")
    user: Mapped[User | None] = relationship()
