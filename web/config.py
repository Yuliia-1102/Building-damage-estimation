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


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOADS_DIR, RESULTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
