"""Statistics across all applications, or one project (section 8). Simulated excluded unless asked."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from web import service
from web.db import session_scope
from web.templating import render

router = APIRouter()


@router.get("/statistics", response_class=HTMLResponse)
def statistics_page(request: Request):
    include_sim = request.query_params.get("include_simulated") == "1"
    project_id = request.query_params.get("project_id")
    pid = int(project_id) if project_id else None
    with session_scope() as s:
        stats = service.statistics(s, project_id=pid, include_simulated=include_sim)
        projects = service.projects(s)
        return render("statistics.html", request, stats=stats, projects=projects,
                      include_simulated=include_sim, project_id=pid, has_simulated=service.has_simulated(s))
