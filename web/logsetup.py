"""Log file shared by the server and the worker: <data>/logs/web.log (rotated at 5 MB, 3 old files kept).

Lines from web.access (one per request, with the request id), web.audit (one per audit record, same request id)
and web.worker (processing). tools/ops_report.py reads this file for the operations report.
"""
import logging
from logging.handlers import RotatingFileHandler

from web import config


def setup_logging() -> None:
    config.ensure_dirs()
    root = logging.getLogger("web")
    if any(getattr(h, "_web_file", False) for h in root.handlers):
        return
    handler = RotatingFileHandler(config.LOGS_DIR / "web.log", maxBytes=5_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler._web_file = True
    root.addHandler(handler)
    root.setLevel(logging.INFO)
