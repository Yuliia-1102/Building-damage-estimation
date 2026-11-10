"""Database tables for the web system (docs/web_system.md, section 6).

application        one operator request: files, status, the engine result, a copy of summary for fast filtering
application_file   one uploaded file of an application, with its sha256 (duplicate control, section 7)
project            a named group of applications (a street, a community)
status_change      the history of status transitions, one row per change
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


UA_STATUS = {
    Status.CREATED: "Створено",
    Status.PROCESSING: "Обробляється",
    Status.PROCESSED: "Оброблено",
    Status.APPROVED: "Затверджено",
    Status.DECLINED: "Відхилено",
    Status.FAILED: "Збій",
}


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    applications: Mapped[list["Application"]] = relationship(back_populates="project")


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(20), default=Status.CREATED, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), default=None, index=True)
    mode: Mapped[str | None] = mapped_column(String(10), default=None)   # photo / photos / video

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

    application: Mapped[Application] = relationship(back_populates="history")
