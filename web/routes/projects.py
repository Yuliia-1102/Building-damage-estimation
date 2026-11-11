"""Projects: a named group of applications with a combined cost estimate (section 8)."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web import service
from web.db import session_scope
from web.models import Application, Project, Status
from web.templating import render

router = APIRouter()


@router.get("/projects", response_class=HTMLResponse)
def projects_list(request: Request):
    with session_scope() as s:
        projects = service.projects(s)
        counts = {p.id: len(p.applications) for p in projects}
        return render("projects.html", request, projects=projects, counts=counts)


@router.post("/projects")
def create_project(name: str = Form(...), description: str = Form("")):
    name = (name or "").strip()
    with session_scope() as s:
        if name:
            s.add(Project(name=name, description=(description or "").strip() or None))
    return RedirectResponse("/projects", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(project_id: int, request: Request):
    with session_scope() as s:
        project = s.get(Project, project_id)
        if project is None:
            return HTMLResponse("Проєкт не знайдено", status_code=404)
        apps = service.board_applications(s, {"project_id": project_id})
        stats = service.statistics(s, project_id=project_id)
        # Cost sums over processed applications with an assessment.
        processed = [a for a in apps if a.has_assessment and a.cost_total]
        approved = [a for a in processed if a.status == Status.APPROVED]
        sums = {
            "all_low": sum(a.cost_low or 0 for a in processed),
            "all_high": sum(a.cost_high or 0 for a in processed),
            "all_total": sum(a.cost_total or 0 for a in processed),
            "appr_low": sum(a.cost_low or 0 for a in approved),
            "appr_high": sum(a.cost_high or 0 for a in approved),
            "appr_total": sum(a.cost_total or 0 for a in approved),
            "no_assessment": sum(1 for a in apps if a.has_assessment is False),
        }
        return render("project.html", request, project=project, apps=apps, stats=stats, sums=sums)
