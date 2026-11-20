"""Paths and limits for the web system, read from the project config (core.config) so nothing is hardcoded twice.

Everything lives under the repository's `data/` folder (already in .gitignore):
    data/web.db                 the web database (applications, files, projects, status history)
    data/uploads/<app_id>/      the files the operator uploaded for an application
    data/results/<app_id>/      the result folder the engine wrote (result.json, report.pdf, views/)
"""
import os
from pathlib import Path

from core import config

ROOT: Path = config.ROOT
# Tests and alternate deployments can point the whole data folder elsewhere (DAMAGE_WEB_DATA=/tmp/...).
DATA_DIR: Path = Path(os.environ.get("DAMAGE_WEB_DATA") or (ROOT / "data"))
DB_PATH: Path = DATA_DIR / "web.db"
UPLOADS_DIR: Path = DATA_DIR / "uploads"
RESULTS_DIR: Path = DATA_DIR / "results"
LOGS_DIR: Path = DATA_DIR / "logs"            # web.log: one line per request and per audit record
BACKUPS_DIR: Path = DATA_DIR / "backups"      # python -m web.backup create

DB_URL = f"sqlite:///{DB_PATH}"

# Upload limits mirror the evaluation side (config.toml [ui] / core.service.input_mode).
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_EXTS = IMAGE_EXTS | VIDEO_EXTS


def max_upload_mb() -> int:
    try:
        return int(config.get("ui", "max_upload_mb"))
    except Exception:
        return 300


class DataDirError(RuntimeError):
    """The configured data folder does not exist (see check_data_dir)."""


def check_data_dir() -> None:
    """Stop when DAMAGE_WEB_DATA points to a folder that does not exist.

    Without this check a typo in the path silently created a new, empty database: the server started, the
    board was empty and new applications went to a database the worker did not read (incident drill,
    20 Nov 2026). The default data/ folder is still created on the first start.
    """
    env = os.environ.get("DAMAGE_WEB_DATA")
    if env and not Path(env).is_dir():
        raise DataDirError(f"DAMAGE_WEB_DATA={env} does not exist. Fix the path, or create the folder "
                           f"first if a new empty database is really wanted.")


def ensure_dirs() -> None:
    check_data_dir()
    for d in (DATA_DIR, UPLOADS_DIR, RESULTS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
