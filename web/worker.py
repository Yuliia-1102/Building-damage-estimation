"""Background worker: the only place the engine runs. Start it in its own process:

    DAMAGE_ENGINE=simulator python -m web.worker          # development
    DAMAGE_ENGINE=real      python -m web.worker          # at integration, with the model weights present

It loops: take the oldest queued application, mark it Processing, run core.service.get_engine().process(),
save the result folder and copy the summary into the row. It talks to the web server only through the
database, so the server can restart, the tab can close, and processing still finishes (section 3).
On startup, applications left in Processing (a previous worker crashed) are returned to the queue.
"""
import logging
import time
from datetime import datetime
from pathlib import Path

from core.service import InputError, get_engine
from web import config, service
from web.db import init_db, session_scope
from web.models import Status

log = logging.getLogger("web.worker")

IDLE_SLEEP = 1.5          # seconds to wait when the queue is empty
PROGRESS_EVERY = 1.0      # write progress to the database at most once per second (section 3)


def _finalize_success(app_id: int, data: dict, result_dir: Path) -> None:
    with session_scope() as s:
        app = service.get(s, app_id)
        if app is None:
            return
        app.result_dir = str(result_dir)
        app.mode = data.get("mode", app.mode)
        app.apply_summary(data["summary"], data.get("revision", 1), data.get("simulated", False))
        app.updated_at = datetime.now()
        service.transition(s, app, Status.PROCESSED)


def _finalize_failure(app_id: int, message: str) -> None:
    with session_scope() as s:
        app = service.get(s, app_id)
        if app is None:
            return
        app.error = message
        app.updated_at = datetime.now()
        service.transition(s, app, Status.FAILED)


def process_one(engine, app_id: int) -> None:
    with session_scope() as s:
        app = service.get(s, app_id)
        if app is None:
            return
        inputs = [Path(f.path) for f in app.files]
    out_dir = config.RESULTS_DIR / str(app_id)

    last = [0.0]

    def on_progress(share: float, text: str) -> None:
        now = time.time()
        if now - last[0] < PROGRESS_EVERY and 0.0 < share < 1.0:
            return
        last[0] = now
        with session_scope() as s:
            app = service.get(s, app_id)
            if app and app.status == Status.PROCESSING:
                app.progress = float(share)
                app.progress_text = text

    try:
        data = engine.process(inputs, out_dir=out_dir, case_id=str(app_id), progress=on_progress)
    except InputError as e:
        log.warning("application %s rejected: %s", app_id, e)
        _finalize_failure(app_id, f"Неприйнятні файли: {e}")
    except Exception as e:   # noqa: BLE001  - any failure => Failed, operator can retry
        log.exception("application %s failed", app_id)
        _finalize_failure(app_id, getattr(e, "user_message", None) or f"{type(e).__name__}: {e}")
    else:
        _finalize_success(app_id, data, out_dir)
        log.info("application %s processed", app_id)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    with session_scope() as s:
        requeued = service.requeue_stuck(s)
    if requeued:
        log.info("requeued %d stuck application(s) after restart", requeued)

    engine = get_engine()
    log.info("worker started, engine=%s", engine.name)
    while True:
        with session_scope() as s:
            app = service.claim_next(s)
            app_id = app.id if app else None
        if app_id is None:
            time.sleep(IDLE_SLEEP)
            continue
        process_one(engine, app_id)


if __name__ == "__main__":
    run()
