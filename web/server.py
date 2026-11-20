"""FastAPI application for the operator web system.

Run (development, simulated engine):
    DAMAGE_ENGINE=simulator uvicorn web.server:app --reload
    DAMAGE_ENGINE=simulator python -m web.worker          # in a second terminal

The server renders the board, the application page, projects and statistics. It never processes an
application itself: it writes rows to the database, and the worker process does the work (web/worker.py).
"""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from web import config
from web.db import init_db, session_scope
from web.models import Application, Status

HERE = Path(__file__).resolve().parent

# An application waiting in the queue longer than this means the worker is not running.
STUCK_QUEUE_MINUTES = 5


def create_app() -> FastAPI:
    config.ensure_dirs()
    init_db()

    app = FastAPI(title="Оцінка пошкоджень — операторська система")

    # Result folders are self-contained static files: /results/<id>/views/view1_overlay.jpg
    app.mount("/results", StaticFiles(directory=str(config.RESULTS_DIR)), name="results")
    static_dir = HERE / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from web.routes import applications, materials, projects, statistics
    app.include_router(applications.router)
    app.include_router(projects.router)
    app.include_router(statistics.router)
    app.include_router(materials.router)

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
        except Exception as e:
            return JSONResponse({"ok": False, "db": "error", "detail": str(e)[:200]}, status_code=503)
        ok = stuck == 0
        return JSONResponse({"ok": ok, "db": "ok", "stuck_in_queue": stuck}, status_code=200 if ok else 503)

    return app


app = create_app()
