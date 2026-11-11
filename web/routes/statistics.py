"""Statistics across all applications, or one project."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from web import service
from web.db import session_scope
from web.templating import render

router = APIRouter()


@router.get("/statistics", response_class=HTMLResponse)
def statistics_page(request: Request):
    project_id = request.query_params.get("project_id")
    pid = int(project_id) if project_id else None
    with session_scope() as s:
        stats = service.statistics(s, project_id=pid)
        projects = service.projects(s)
        return render("statistics.html", request, stats=stats, projects=projects,
                      project_id=pid)
