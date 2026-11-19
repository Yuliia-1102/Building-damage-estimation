"""Backup and restore of the web system's data (v2.0).

    python -m web.backup create                 # -> <data>/backups/backup-YYYYmmdd-HHMMSS.zip
    python -m web.backup restore <file.zip>     # replaces the data folder contents with the backup
    python -m web.backup verify <file.zip>      # compares the current data with the backup's manifest

A backup holds: web.db (a consistent copy made with SQLite's backup API, so it can be taken while the server
runs), the uploaded files, the result folders, the materials/prices database, and manifest.json with the row
counts (web.migrate.report) and the data folder it was taken from.

Restore: stop the server and the worker first. File paths in the database are rewritten from the old data
folder to the new one, so a backup can be restored on another computer (the handover check). After the
restore the counts are compared with the manifest and every file the database points to must exist.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from core import config as core_config
from web import config


def _materials_db() -> Path:
    return core_config.path("materials_db")


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=core_config.ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _sqlite_copy(src: Path, dst: Path) -> None:
    with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
        a.backup(b)


def _report(db: Path) -> dict:
    from web.migrate import report
    engine = create_engine(f"sqlite:///{db}")
    try:
        return report(engine)
    finally:
        engine.dispose()


def create(out_dir: Path | None = None) -> Path:
    out_dir = out_dir or config.BACKUPS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
    target = out_dir / name
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _sqlite_copy(config.DB_PATH, tmp / "web.db")
        manifest = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "commit": _commit(),
            "data_dir": str(config.DATA_DIR),
            "report": _report(tmp / "web.db"),
            "materials_db": _materials_db().exists(),
        }
        if manifest["materials_db"]:
            _sqlite_copy(_materials_db(), tmp / "materials.db")
        (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for f in ("web.db", "materials.db", "manifest.json"):
                if (tmp / f).exists():
                    z.write(tmp / f, f)
            for folder in (config.UPLOADS_DIR, config.RESULTS_DIR):
                for p in sorted(folder.rglob("*")):
                    if p.is_file():
                        z.write(p, f"{folder.name}/{p.relative_to(folder)}")
    return target


def _rewrite_paths(db: Path, old_dir: str, new_dir: str) -> int:
    if old_dir == new_dir:
        return 0
    with sqlite3.connect(db) as c:
        n = c.execute("UPDATE application_file SET path = replace(path, ?, ?) WHERE path LIKE ?",
                      (old_dir, new_dir, old_dir + "%")).rowcount
        n += c.execute("UPDATE application SET result_dir = replace(result_dir, ?, ?) WHERE result_dir LIKE ?",
                       (old_dir, new_dir, old_dir + "%")).rowcount
    return n


def verify(manifest: dict) -> list[str]:
    """Problems found when comparing the current data with a backup's manifest (empty list = OK)."""
    problems = []
    now = _report(config.DB_PATH)
    for key in ("application", "application_file", "status_change", "project", "app_user", "by_status"):
        if key in manifest["report"] and manifest["report"][key] != now.get(key):
            problems.append(f"{key}: backup {manifest['report'][key]} != now {now.get(key)}")
    engine = create_engine(config.DB_URL)
    with engine.connect() as c:
        for (path,) in c.execute(text("SELECT path FROM application_file")).all():
            if not Path(path).exists():
                problems.append(f"missing file {path}")
    engine.dispose()
    return problems


def restore(archive: Path) -> dict:
    from web.db import engine
    engine.dispose()      # close pooled connections before the database file is replaced
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        config.ensure_dirs()
        for folder in (config.UPLOADS_DIR, config.RESULTS_DIR):
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
        for name in z.namelist():
            if name.startswith(("uploads/", "results/")):
                z.extract(name, config.DATA_DIR)
        for suffix in ("", "-wal", "-shm"):
            Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
        z.extract("web.db", config.DATA_DIR)
        if "materials.db" in z.namelist():
            _materials_db().parent.mkdir(parents=True, exist_ok=True)
            _materials_db().write_bytes(z.read("materials.db"))
    rewritten = _rewrite_paths(config.DB_PATH, manifest["data_dir"], str(config.DATA_DIR))
    return {"manifest": manifest, "paths_rewritten": rewritten, "problems": verify(manifest)}


def main() -> None:
    p = argparse.ArgumentParser(description="Backup and restore of the web system's data")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create")
    r = sub.add_parser("restore")
    r.add_argument("archive", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("archive", type=Path)
    a = p.parse_args()

    if a.cmd == "create":
        path = create()
        manifest = json.loads(zipfile.ZipFile(path).read("manifest.json"))
        print(f"backup: {path}")
        print(json.dumps(manifest["report"], ensure_ascii=False))
    elif a.cmd == "restore":
        result = restore(a.archive)
        print(f"restored from {a.archive} (taken {result['manifest']['created']}, "
              f"commit {result['manifest']['commit']}); file paths rewritten: {result['paths_rewritten']}")
        print(json.dumps(_report(config.DB_PATH), ensure_ascii=False))
        if result["problems"]:
            print("PROBLEMS:\n  " + "\n  ".join(result["problems"]))
            sys.exit(1)
        print("OK: the same applications, files, history and users as in the backup; every file exists")
    else:
        manifest = json.loads(zipfile.ZipFile(a.archive).read("manifest.json"))
        problems = verify(manifest)
        print("OK" if not problems else "PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
