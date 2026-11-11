"""FastAPI application for the operator web system.

Run: scripts/run_production.sh (the server and the worker together).

The server renders the board, the application page, projects and statistics. It never processes an
application itself: it writes rows to the database, and the worker process does the work (web/worker.py).
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from web import config
from web.db import init_db

HERE = Path(__file__).resolve().parent


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
        return {"ok": True}

    return app


app = create_app()
