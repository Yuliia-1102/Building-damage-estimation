"""Applications: the board, creating an application, the application page, the operator's actions.

The engine is never called here except for reevaluate(), which the spec allows in-request (1-3 s). Processing
runs in the worker process (web/worker.py).
"""
import json
from datetime import datetime
from html import escape
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from web import audit, service
from web.auth import can_change
from web.db import session_scope
from web.files import UploadRejected, check_mode, save_uploads
from web.models import Application, Status
from web.templating import render

router = APIRouter()


def error_page(status_code: int, text: str, back: str = "/board") -> HTMLResponse:
    """A short error page. 400 validation, 403 no permission, 404 not found, 409 conflict - never 500."""
    return HTMLResponse(f'<p>{escape(text)}</p><p><a href="{escape(back)}">Назад</a></p>', status_code=status_code)


def _owned(s, request: Request, app_id: int, action: str):
    """Load the application and check that the signed-in user may act on it.

    Returns (app, None) when allowed, or (None, error response) - a refusal is also written to the audit log."""
    user = request.state.user
    app = service.get(s, app_id)
    if app is None:
        return None, error_page(404, "Заявку не знайдено.")
    if not can_change(user, app):
        audit.record(s, user, action, "application", app_id, result="denied", details="not the owner")
        return None, error_page(403, "Немає прав: заявка належить іншому оператору.", f"/applications/{app_id}")
    return app, None


# ---------- board ----------

def _parse_filters(request: Request) -> dict:
    q = request.query_params
    f: dict = {
        "status": q.get("status") or None,
        "damage_category": q.get("damage_category") or None,
        "condition_category": q.get("condition_category") or None,
        "escalation": q.get("escalation") or None,
        "project_id": q.get("project_id") or None,
        "query": q.get("query") or None,
        "mine": q.get("mine") == "1",
        # Show simulated by default (in development every result is simulated, so hiding them empties the
        # board). The toggle only hides them once the operator submits the filter form with it unchecked.
        "show_simulated": True if not q else q.get("show_simulated") == "1",
    }
    for key in ("cost_min", "cost_max"):
        val = q.get(key)
        f[key] = int(val) * 1000 if val else None   # the form takes thousands of UAH
    for key, col in (("date_from", "date_from"), ("date_to", "date_to")):
        val = q.get(key)
        if val:
            try:
                f[col] = datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                f[col] = None
    return f


@router.get("/board", response_class=HTMLResponse)
def board(request: Request):
    filters = _parse_filters(request)
    if filters["mine"]:
        filters["owner_id"] = request.state.user.id
    with session_scope() as s:
        apps = service.board_applications(s, filters)
        projects = service.projects(s)
        columns = {st: [a for a in apps if a.status == st] for st in Status.BOARD}
        return render("board.html", request, columns=columns, projects=projects, filters=filters,
                      raw=dict(request.query_params), total=len(apps), has_simulated=service.has_simulated(s))


# ---------- creating ----------

@router.get("/applications/new", response_class=HTMLResponse)
def new_form(request: Request):
    with session_scope() as s:
        projects = service.projects(s)
    return render("new.html", request, projects=projects, error=None,
                  project_id=request.query_params.get("project_id"))


@router.post("/applications")
async def create(request: Request,
                 title: str = Form(...),
                 comment: str = Form(""),
                 project_id: str = Form(""),
                 files: list[UploadFile] = File(...)):
    uploads = [f for f in files if f and f.filename]
    pid = int(project_id) if project_id else None
    try:
        mode = check_mode([f.filename for f in uploads])
    except UploadRejected as e:
        with session_scope() as s:
            projects = service.projects(s)
        return render("new.html", request, projects=projects, error=str(e), project_id=project_id)

    with session_scope() as s:
        user = request.state.user
        app = service.new_application_row(s, title=title, comment=comment, project_id=pid, mode=mode,
                                          owner_id=user.id)
        app_id = app.id
        try:
            saved = save_uploads(app_id, uploads)
        except UploadRejected as e:
            s.rollback()
            with session_scope() as s2:
                projects = service.projects(s2)
            return render("new.html", request, projects=projects, error=str(e), project_id=project_id)
        dup = service.attach_files_and_queue(s, app, saved)
        dup_id = dup.id if dup else None
        audit.record(s, user, "application_created", "application", app_id,
                     details=f"title={app.title!r} mode={mode} project={pid or '-'} files={len(saved)}"
                             + (f" duplicate_of={dup_id}" if dup_id else ""))
        for f in saved:
            audit.record(s, user, "file_uploaded", "application", app_id,
                         details=f"{f['name']} {f['bytes']} bytes sha256={f['sha256'][:12]}")

    target = f"/applications/{app_id}" + ("?dup=1" if dup_id else "")
    return RedirectResponse(target, status_code=303)


# ---------- application page ----------

def _load_result(app: Application) -> dict | None:
    if not app.result_dir:
        return None
    p = Path(app.result_dir) / "result.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/applications/{app_id}", response_class=HTMLResponse)
def detail(app_id: int, request: Request):
    with session_scope() as s:
        app = service.get(s, app_id)
        if app is None:
            return HTMLResponse("Заявку не знайдено", status_code=404)
        result = _load_result(app)
        duplicate_of = service.get(s, app.duplicate_of_id) if app.duplicate_of_id else None
        show_dup_warning = request.query_params.get("dup") == "1" and app.is_duplicate
        projects = service.projects(s)
        return render("application.html", request, app=app, result=result, wall=_wall_steps(result, app),
                      duplicate_of=duplicate_of, show_dup_warning=show_dup_warning, projects=projects)


def _wall_steps(result: dict | None, app: Application) -> list[str]:
    """How the wall works were computed, in square metres (the same text as in the PDF)."""
    if not result or not app.has_assessment:
        return []
    from core.report_pdf import wall_steps
    from core.service import report_from_dict
    report = report_from_dict(result["report"])
    if report.decision is None or report.decision.facade is None or not report.decision.works:
        return []
    return wall_steps(report.decision, report.building, report.areas)


@router.get("/applications/{app_id}/progress", response_class=HTMLResponse)
def progress(app_id: int, request: Request):
    """HTMX polls this while an application is processing; it swaps in the progress/badges fragment."""
    with session_scope() as s:
        app = service.get(s, app_id)
        if app is None:
            return HTMLResponse("", status_code=404)
        done = app.status not in (Status.CREATED, Status.PROCESSING)
        response = render("partials/progress.html", request, app=app, done=done)
        if done:
            response.headers["HX-Refresh"] = "true"   # reload the full page with the result
        return response


# ---------- operator actions ----------

@router.post("/applications/{app_id}/retry")
def retry(app_id: int, request: Request):
    with session_scope() as s:
        app, denied = _owned(s, request, app_id, "application_retried")
        if denied:
            return denied
        if app.can_retry:
            service.transition(s, app, Status.CREATED, comment="повторна обробка", user=request.state.user)
            audit.record(s, request.state.user, "application_retried", "application", app_id)
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/approve")
def approve(app_id: int, request: Request):
    user = request.state.user
    with session_scope() as s:
        app, denied = _owned(s, request, app_id, "application_approved")
        if denied:
            return denied
        if not app.has_assessment:
            return error_page(400, "Без оцінки заявку не можна затвердити.", f"/applications/{app_id}")
        try:
            service.decide(s, app_id, Status.APPROVED, comment=f"затверджено: {user.display_name}", user=user)
            audit.record(s, user, "application_approved", "application", app_id)
        except service.Conflict:
            return error_page(409, "Заявка вже не очікує рішення: її змінив хтось інший.",
                              f"/applications/{app_id}")
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/decline")
def decline(app_id: int, request: Request, reason: str = Form(...)):
    user = request.state.user
    reason = (reason or "").strip()
    with session_scope() as s:
        _, denied = _owned(s, request, app_id, "application_declined")
        if denied:
            return denied
        if not reason:
            return error_page(400, "Вкажіть причину відхилення.", f"/applications/{app_id}")
        try:
            service.decide(s, app_id, Status.DECLINED, comment=reason, user=user)
            audit.record(s, user, "application_declined", "application", app_id, details=reason)
        except service.Conflict:
            return error_page(409, "Заявка вже не очікує рішення: її змінив хтось інший.",
                              f"/applications/{app_id}")
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/reopen")
def reopen(app_id: int, request: Request):
    with session_scope() as s:
        app, denied = _owned(s, request, app_id, "application_reopened")
        if denied:
            return denied
        if app.status in (Status.APPROVED, Status.DECLINED):
            service.transition(s, app, Status.PROCESSED, comment="повернено на розгляд", user=request.state.user)
            audit.record(s, request.state.user, "application_reopened", "application", app_id)
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/assign")
def assign_project(app_id: int, request: Request, project_id: str = Form("")):
    with session_scope() as s:
        app, denied = _owned(s, request, app_id, "project_assigned")
        if denied:
            return denied
        app.project_id = int(project_id) if project_id else None
        audit.record(s, request.state.user, "project_assigned", "application", app_id,
                     details=f"project={app.project_id or '-'}")
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


ALLOWED_PARAMS = {"floors": int, "floor_height_m": float, "width_m": float, "depth_m": float}


@router.post("/applications/{app_id}/reevaluate")
def reevaluate(app_id: int, request: Request,
               floors: str = Form(""), floor_height_m: str = Form(""),
               width_m: str = Form(""), depth_m: str = Form(""),
               roof_type: str = Form(""), structure_type: str = Form("")):
    """Operator corrected building parameters: recompute areas/decision/cost without re-segmenting (section 3)."""
    raw = {"floors": floors, "floor_height_m": floor_height_m, "width_m": width_m, "depth_m": depth_m}
    changes: dict = {}
    for key, caster in ALLOWED_PARAMS.items():
        val = (raw[key] or "").strip()
        if val:
            try:
                changes[key] = caster(val.replace(",", "."))
            except ValueError:
                pass
    if roof_type in ("flat", "pitched"):
        changes["roof_type"] = roof_type
    if structure_type.strip():
        changes["structure_type"] = structure_type.strip()

    error = None
    with session_scope() as s:
        app, denied = _owned(s, request, app_id, "parameters_corrected")
        if denied:
            return denied
        if app.status != Status.PROCESSED or not app.result_dir:
            error = "Перерахунок доступний лише для оброблених заявок."
        elif not changes:
            error = "Не вказано жодного параметра для зміни."
        else:
            from core.service import InputError, get_engine
            try:
                data = get_engine().reevaluate(Path(app.result_dir), changes)
                app.apply_summary(data["summary"], data.get("revision", app.revision + 1),
                                  data.get("simulated", app.simulated))
                app.updated_at = datetime.now()
                s.add(service.StatusChange(application_id=app.id, from_status=Status.PROCESSED,
                                           to_status=Status.PROCESSED, user_id=request.state.user.id,
                                           comment="оператор змінив параметри будівлі, перерахунок"))
                audit.record(s, request.state.user, "parameters_corrected", "application", app_id,
                             details=json.dumps(changes, ensure_ascii=False))
            except InputError as e:
                error = f"Неприйнятні параметри: {e}"
            except Exception as e:   # noqa: BLE001
                error = f"Помилка перерахунку: {e}"
    suffix = "?err=" + error.replace(" ", "+") if error else "?recomputed=1"
    return RedirectResponse(f"/applications/{app_id}{suffix}", status_code=303)


@router.post("/applications/{app_id}/dedupe")
def dedupe(app_id: int, request: Request, action: str = Form(...)):
    """Resolve a duplicate warning: reject / merge / continue (section 7)."""
    user = request.state.user
    with session_scope() as s:
        app, denied = _owned(s, request, app_id, "duplicate_resolved")
        if denied:
            return denied
        if not app.is_duplicate:
            return RedirectResponse(f"/applications/{app_id}", status_code=303)
        other_id = app.duplicate_of_id
        if action == "reject":
            service.transition(s, app, Status.DECLINED, comment=f"дублікат заявки №{other_id}", user=user)
        elif action == "merge":
            service.merge_into(s, app, user=user)
        else:  # continue
            service.queue_application(s, app)
            s.add(service.StatusChange(application_id=app.id, from_status=Status.CREATED,
                                       to_status=Status.CREATED, user_id=user.id,
                                       comment="оператор продовжив попри можливий дублікат"))
        audit.record(s, user, "duplicate_resolved", "application", app_id,
                     details=f"action={action} duplicate_of={other_id}")
    return RedirectResponse(f"/applications/{other_id if action in ('reject', 'merge') else app_id}",
                            status_code=303)
