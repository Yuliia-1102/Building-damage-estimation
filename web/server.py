"""FastAPI application for the operator web system.

Run (development, simulated engine):
    DAMAGE_ENGINE=simulator uvicorn web.server:app --reload
    DAMAGE_ENGINE=simulator python -m web.worker          # in a second terminal

The server renders the board, the application page, projects and statistics. It never processes an
application itself: it writes rows to the database, and the worker process does the work (web/worker.py).

v2.0: every page except /login, /healthz and /static needs a signed-in user (web/auth.py). Every request gets
a short request id; the id, the user, the path, the status and the duration go into <data>/logs/web.log, and
the same id is stored with the audit records of that request, so one failed operation can be traced from the
log line to the audit row and the application (docs/v2/observability.md).
"""
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from web import audit, config
from web.auth import COOKIE, user_from_cookie
from web.db import init_db, session_scope
from web.logsetup import setup_logging
from web.models import Application, Status

HERE = Path(__file__).resolve().parent
PUBLIC = ("/login", "/healthz", "/static/")

access_log = logging.getLogger("web.access")

# An application waiting in the queue longer than this means the worker is not running.
STUCK_QUEUE_MINUTES = 5


def create_app() -> FastAPI:
    config.ensure_dirs()
    setup_logging()
    init_db()

    app = FastAPI(title="Оцінка пошкоджень — операторська система")

    @app.middleware("http")
    async def auth_and_log(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        token = audit.request_id.set(rid)
        started = time.perf_counter()
        request.state.user = None
        status = 500
        try:
            with session_scope() as s:
                request.state.user = user_from_cookie(s, request.cookies.get(COOKIE))
            path = request.url.path
            if request.state.user is None and not path.startswith(PUBLIC):
                status = 303
                return RedirectResponse(f"/login?next={path}", status_code=303)
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            ms = (time.perf_counter() - started) * 1000
            user = request.state.user.username if request.state.user else "-"
            outcome = "ok" if status < 400 else ("fail" if status >= 500 else "rejected")
            access_log.info("request rid=%s user=%s method=%s path=%s status=%s outcome=%s ms=%.1f",
                            rid, user, request.method, request.url.path, status, outcome, ms)
            audit.request_id.reset(token)

    # Result folders are self-contained static files: /results/<id>/views/view1_overlay.jpg
    app.mount("/results", StaticFiles(directory=str(config.RESULTS_DIR)), name="results")
    static_dir = HERE / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from web.routes import admin, applications, auth, materials, projects, statistics
    app.include_router(auth.router)
    app.include_router(applications.router)
    app.include_router(projects.router)
    app.include_router(statistics.router)
    app.include_router(materials.router)
    app.include_router(admin.router)

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/board")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """200 if the system works; 503 if the database is unreachable or the queue does not move."""
        try:
            with session_scope() as s:
                s.execute(text("SELECT 1"))
                limit = datetime.now() - timedelta(minutes=STUCK_QUEUE_MINUTES)
                stuck = s.scalar(select(func.count()).select_from(Application).where(
                    Application.status == Status.CREATED, Application.queued_at < limit))
        except Exception:
            # the details stay in the log: /healthz is public and must not show server paths or errors
            logging.getLogger("web.health").exception("healthz: database check failed")
            return JSONResponse({"ok": False, "db": "error"}, status_code=503)
        ok = stuck == 0
        return JSONResponse({"ok": ok, "db": "ok", "stuck_in_queue": stuck}, status_code=200 if ok else 503)

    return app


app = create_app()
