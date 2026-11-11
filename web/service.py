"""Business logic over the database: it never imports FastAPI and never touches the engine, so both the web
server and the worker call the same functions. Engine calls live in web/worker.py.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from web import config
from web.models import Application, ApplicationFile, Project, Status, StatusChange


# ---------- status transitions ----------

def transition(session: Session, app: Application, to_status: str, comment: str | None = None) -> None:
    """Change an application's status and record it in status_change with the right timestamps."""
    frm = app.status
    now = datetime.now()
    app.status = to_status
    if to_status == Status.CREATED:
        app.queued_at = now
        app.started_at = None
        app.progress = 0.0
        app.progress_text = ""
        app.error = None
    elif to_status == Status.PROCESSING:
        app.started_at = now
    elif to_status in (Status.PROCESSED, Status.FAILED):
        app.finished_at = now
    elif to_status in (Status.APPROVED, Status.DECLINED):
        app.decided_at = now
        if comment:
            app.decision_comment = comment
    session.add(StatusChange(application_id=app.id, from_status=frm, to_status=to_status, comment=comment))


# ---------- creating applications ----------

def new_application_row(session: Session, *, title: str, comment: str | None, project_id: int | None,
                        mode: str) -> Application:
    """Create the application row (so files can be saved under data/uploads/<id>/) and record Created."""
    app = Application(title=(title or "").strip() or "Без назви", comment=(comment or "").strip() or None,
                      project_id=project_id, mode=mode, status=Status.CREATED)
    session.add(app)
    session.flush()   # assign app.id
    session.add(StatusChange(application_id=app.id, from_status=None, to_status=Status.CREATED))
    return app


def attach_files_and_queue(session: Session, app: Application, saved: list[dict]) -> Application | None:
    """Attach already-saved files to the application, then either queue it or flag a duplicate (section 7).

    Returns the duplicate the files match (and leaves the application un-queued), or None when it was queued.
    """
    for f in saved:
        session.add(ApplicationFile(application_id=app.id, name=f["name"], path=f["path"],
                                    bytes=f["bytes"], sha256=f["sha256"]))
    dup = find_duplicate(session, [f["sha256"] for f in saved], exclude_app_id=app.id)
    if dup is not None:
        app.duplicate_of_id = dup.id
        app.progress_text = f"Можливий дублікат заявки №{dup.id}"
    else:
        app.queued_at = datetime.now()
    session.flush()
    return dup


def merge_into(session: Session, app: Application) -> Application | None:
    """Merge a duplicate application into the one it duplicates (section 7).

    Files of `app` that the target does not already have (by sha256) are copied into the target; the target
    goes back to Created and is re-processed with all files (more views, better estimate). `app` becomes
    Declined and merged (excluded from future duplicate search)."""
    import shutil

    target = session.get(Application, app.duplicate_of_id) if app.duplicate_of_id else None
    if target is None:
        return None
    have = {f.sha256 for f in target.files}
    dest = config.UPLOADS_DIR / str(target.id)
    dest.mkdir(parents=True, exist_ok=True)
    added = 0
    for f in app.files:
        if f.sha256 in have:
            continue
        src = Path(f.path)
        new_path = dest / src.name
        if new_path.exists():
            new_path = dest / f"dup{app.id}_{src.name}"
        try:
            shutil.copy2(src, new_path)
        except OSError:
            continue
        session.add(ApplicationFile(application_id=target.id, name=new_path.name, path=str(new_path),
                                    bytes=f.bytes, sha256=f.sha256))
        have.add(f.sha256)
        added += 1

    app.merged = True
    transition(session, app, Status.DECLINED, comment=f"об'єднано із заявкою №{target.id}")
    if added:
        transition(session, target, Status.CREATED,
                   comment=f"додано {added} файл(и) із заявки №{app.id}, повторна обробка")
        target.queued_at = datetime.now()
    session.flush()
    return target


def queue_application(session: Session, app: Application) -> None:
    """Put a Created application into the worker queue (used after the operator resolves a duplicate warning)."""
    app.queued_at = datetime.now()
    app.progress_text = ""
    session.flush()


def find_duplicate(session: Session, hashes: list[str], exclude_app_id: int | None = None) -> Application | None:
    """The earliest non-merged application (other than exclude_app_id) that has a file with one of these hashes."""
    if not hashes:
        return None
    stmt = (select(Application)
            .join(ApplicationFile, ApplicationFile.application_id == Application.id)
            .where(ApplicationFile.sha256.in_(hashes), Application.merged.is_(False))
            .order_by(Application.id))
    if exclude_app_id is not None:
        stmt = stmt.where(Application.id != exclude_app_id)
    return session.scalars(stmt).first()


# ---------- worker coordination ----------

def requeue_stuck(session: Session) -> int:
    """On worker startup, applications left in Processing (the worker crashed) go back to Created (section 3)."""
    stuck = session.scalars(select(Application).where(Application.status == Status.PROCESSING)).all()
    for app in stuck:
        transition(session, app, Status.CREATED, comment="повернено в чергу після перезапуску обробника")
    return len(stuck)


def claim_next(session: Session) -> Application | None:
    """Atomically take the oldest queued Created application and mark it Processing, so two workers cannot take
    the same one. Returns the claimed application or None if the queue is empty."""
    app = session.scalars(
        select(Application)
        .where(Application.status == Status.CREATED, Application.queued_at.is_not(None))
        .order_by(Application.queued_at)
        .limit(1)
    ).first()   # SQLite has no row locks; the immediate commit of Processing below is the guard (one worker)
    if app is None:
        return None
    transition(session, app, Status.PROCESSING)
    session.commit()
    return app


# ---------- queries for the board / pages ----------

def get(session: Session, app_id: int) -> Application | None:
    return session.get(Application, app_id)


def board_applications(session: Session, filters: dict | None = None) -> list[Application]:
    filters = filters or {}
    stmt = select(Application)
    if filters.get("status"):
        stmt = stmt.where(Application.status == filters["status"])
    if filters.get("damage_category"):
        stmt = stmt.where(Application.damage_category == filters["damage_category"])
    if filters.get("condition_category"):
        stmt = stmt.where(Application.condition_category == int(filters["condition_category"]))
    if filters.get("escalation"):
        stmt = stmt.where(Application.escalation == filters["escalation"])
    if filters.get("project_id"):
        stmt = stmt.where(Application.project_id == int(filters["project_id"]))
    if filters.get("cost_min") is not None:
        stmt = stmt.where(Application.cost_high >= filters["cost_min"])
    if filters.get("cost_max") is not None:
        stmt = stmt.where(Application.cost_low <= filters["cost_max"])
    if filters.get("query"):
        stmt = stmt.where(Application.title.ilike(f"%{filters['query']}%"))
    if filters.get("date_from"):
        stmt = stmt.where(Application.created_at >= filters["date_from"])
    if filters.get("date_to"):
        stmt = stmt.where(Application.created_at <= filters["date_to"])
    stmt = stmt.order_by(Application.created_at.desc())
    return list(session.scalars(stmt).all())


def projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.name)).all())


# ---------- statistics (section 8) ----------

def statistics(session: Session, *, project_id: int | None = None) -> dict:
    stmt = select(Application)
    if project_id is not None:
        stmt = stmt.where(Application.project_id == project_id)
    apps = list(session.scalars(stmt).all())

    by_status = {s: 0 for s in Status.ALL}
    by_damage = {"I": 0, "II": 0, "III": 0}
    by_condition = {1: 0, 2: 0, 3: 0, 4: 0}
    approved_cost_low = approved_cost_high = approved_cost_total = 0
    durations: list[float] = []
    duplicates = merged = 0
    no_assessment = 0

    for a in apps:
        by_status[a.status] = by_status.get(a.status, 0) + 1
        if a.damage_category in by_damage:
            by_damage[a.damage_category] += 1
        if a.condition_category in by_condition:
            by_condition[a.condition_category] += 1
        if a.status == Status.APPROVED and a.cost_total:
            approved_cost_low += a.cost_low or 0
            approved_cost_high += a.cost_high or 0
            approved_cost_total += a.cost_total or 0
        if a.started_at and a.finished_at:
            durations.append((a.finished_at - a.started_at).total_seconds())
        if a.is_duplicate:
            duplicates += 1
        if a.merged:
            merged += 1
        if a.has_assessment is False:
            no_assessment += 1

    total = len(apps)
    failed = by_status.get(Status.FAILED, 0)
    return {
        "total": total,
        "by_status": by_status,
        "by_damage": by_damage,
        "by_condition": by_condition,
        "approved": by_status.get(Status.APPROVED, 0),
        "declined": by_status.get(Status.DECLINED, 0),
        "approved_cost_low": approved_cost_low,
        "approved_cost_high": approved_cost_high,
        "approved_cost_total": approved_cost_total,
        "avg_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "fail_rate": round(failed / total, 2) if total else 0.0,
        "duplicates": duplicates,
        "merged": merged,
        "no_assessment": no_assessment,
    }
