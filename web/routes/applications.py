"""Applications: the board, creating an application, the application page, the operator's actions.

The engine is never called here except for reevaluate(), which the spec allows in-request (1-3 s). Processing
runs in the worker process (web/worker.py).
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from web import service
from web.db import session_scope
from web.files import UploadRejected, check_mode, save_uploads
from web.models import Application, Status
from web.templating import render

router = APIRouter()


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
    with session_scope() as s:
        apps = service.board_applications(s, filters)
        projects = service.projects(s)
        columns = {st: [a for a in apps if a.status == st] for st in Status.BOARD}
        return render("board.html", request, columns=columns, projects=projects,
                      filters=filters, raw=dict(request.query_params), total=len(apps))


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
        app = service.new_application_row(s, title=title, comment=comment, project_id=pid, mode=mode)
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
        return render("application.html", request, app=app, result=result,
                      duplicate_of=duplicate_of, show_dup_warning=show_dup_warning, projects=projects)


@router.get("/applications/{app_id}/progress", response_class=HTMLResponse)
def progress(app_id: int, request: Request):
    """HTMX polls this while an application is processing; it swaps in the progress/badges fragment."""
    with session_scope() as s:
        app = service.get(s, app_id)
        if app is None:
            return HTMLResponse("", status_code=404)
        done = app.status not in (Status.CREATED, Status.PROCESSING)
        return render("partials/progress.html", request, app=app, done=done)


# ---------- operator actions ----------

@router.post("/applications/{app_id}/retry")
def retry(app_id: int):
    with session_scope() as s:
        app = service.get(s, app_id)
        if app and app.can_retry:
            service.transition(s, app, Status.CREATED, comment="повторна обробка")
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/approve")
def approve(app_id: int):
    with session_scope() as s:
        app = service.get(s, app_id)
        if app and app.can_decide and app.has_assessment:
            service.transition(s, app, Status.APPROVED, comment="затверджено оператором")
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/decline")
def decline(app_id: int, reason: str = Form(...)):
    reason = (reason or "").strip()
    with session_scope() as s:
        app = service.get(s, app_id)
        if app and app.can_decide and reason:
            service.transition(s, app, Status.DECLINED, comment=reason)
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/reopen")
def reopen(app_id: int):
    with session_scope() as s:
        app = service.get(s, app_id)
        if app and app.status in (Status.APPROVED, Status.DECLINED):
            service.transition(s, app, Status.PROCESSED, comment="повернено на розгляд")
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@router.post("/applications/{app_id}/assign")
def assign_project(app_id: int, project_id: str = Form("")):
    with session_scope() as s:
        app = service.get(s, app_id)
        if app:
            app.project_id = int(project_id) if project_id else None
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


ALLOWED_PARAMS = {"floors": int, "floor_height_m": float, "width_m": float, "depth_m": float}


@router.post("/applications/{app_id}/reevaluate")
def reevaluate(app_id: int,
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
        app = service.get(s, app_id)
        if app is None:
            return HTMLResponse("Заявку не знайдено", status_code=404)
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
                                           to_status=Status.PROCESSED,
                                           comment="оператор змінив параметри будівлі, перерахунок"))
            except InputError as e:
                error = f"Неприйнятні параметри: {e}"
            except Exception as e:   # noqa: BLE001
                error = f"Помилка перерахунку: {e}"
    suffix = "?err=" + error.replace(" ", "+") if error else "?recomputed=1"
    return RedirectResponse(f"/applications/{app_id}{suffix}", status_code=303)


@router.post("/applications/{app_id}/dedupe")
def dedupe(app_id: int, action: str = Form(...)):
    """Resolve a duplicate warning: reject / merge / continue (section 7)."""
    with session_scope() as s:
        app = service.get(s, app_id)
        if app is None or not app.is_duplicate:
            return RedirectResponse(f"/applications/{app_id}", status_code=303)
        other_id = app.duplicate_of_id
        if action == "reject":
            service.transition(s, app, Status.DECLINED, comment=f"дублікат заявки №{other_id}")
        elif action == "merge":
            service.merge_into(s, app)
        else:  # continue
            service.queue_application(s, app)
            s.add(service.StatusChange(application_id=app.id, from_status=Status.CREATED,
                                       to_status=Status.CREATED,
                                       comment="оператор продовжив попри можливий дублікат"))
    return RedirectResponse(f"/applications/{other_id if action in ('reject', 'merge') else app_id}",
                            status_code=303)