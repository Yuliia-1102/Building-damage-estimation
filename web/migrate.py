"""Database migration v1.0 -> v2.0 (accounts, owners, audit log). Safe to run many times.

What changes:
  new tables      app_user, audit_event, schema_version
  new columns     application.owner_id, status_change.user_id, project.created_by_id (all nullable)
  data            the training accounts and the "legacy" user are created; every application without an owner
                  gets the legacy owner. Ids, statuses, dates, files, results and history are not touched.

Run it explicitly (prints the check before and after) - the web server and the worker also run it on start:
    python -m web.migrate                 # the database from DAMAGE_WEB_DATA / data/web.db
    python -m web.migrate --check         # only report, change nothing

Rollback: v1.0 code ignores the new tables and columns, so it still starts on a migrated database, but
applications it creates get no owner and its actions are not audited. Going back fully means restoring the
backup taken before the migration (python -m web.backup restore ...). See docs/v2/migration.md.
"""
from __future__ import annotations

import argparse
import json
import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine

log = logging.getLogger("web.migrate")

CURRENT_VERSION = 2

NEW_COLUMNS = [
    # table, column, SQL type
    ("application", "owner_id", "INTEGER REFERENCES app_user(id)"),
    ("status_change", "user_id", "INTEGER REFERENCES app_user(id)"),
    ("project", "created_by_id", "INTEGER REFERENCES app_user(id)"),
]


def report(engine: Engine) -> dict:
    """Counts and checks used before and after the migration (and after a restore)."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    out: dict = {"tables": sorted(tables)}
    with engine.connect() as c:
        for t in ("application", "application_file", "status_change", "project", "app_user", "audit_event"):
            out[t] = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() if t in tables else None
        if "application" in tables:
            rows = c.execute(text("SELECT status, COUNT(*) FROM application GROUP BY status")).all()
            out["by_status"] = {s: n for s, n in rows}
            cols = {col["name"] for col in insp.get_columns("application")}
            out["without_owner"] = (c.execute(text("SELECT COUNT(*) FROM application WHERE owner_id IS NULL"))
                                    .scalar() if "owner_id" in cols else out["application"])
        out["version"] = (c.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
                          if "schema_version" in tables else 1)
    return out


def migrate(engine: Engine) -> dict:
    """Bring the database to CURRENT_VERSION. Returns {"before": report, "after": report}."""
    from web.auth import ensure_demo_users
    from web.db import Base
    from web.models import LEGACY_USERNAME, Application, SchemaVersion, User

    before = report(engine)
    Base.metadata.create_all(engine)          # creates only the missing tables
    insp = inspect(engine)
    with engine.begin() as c:
        for table, column, sqltype in NEW_COLUMNS:
            if column not in {col["name"] for col in insp.get_columns(table)}:
                c.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}"))
                log.info("migration: added %s.%s", table, column)

    from sqlalchemy.orm import Session
    with Session(engine) as s:
        ensure_demo_users(s)
        legacy = s.scalar(select(User).where(User.username == LEGACY_USERNAME))
        orphans = s.scalars(select(Application).where(Application.owner_id.is_(None))).all()
        for app in orphans:
            app.owner_id = legacy.id
        if s.get(SchemaVersion, CURRENT_VERSION) is None:
            s.add(SchemaVersion(version=CURRENT_VERSION,
                                note=f"accounts, owners, audit log; {len(orphans)} application(s) -> legacy"))
        s.commit()
    after = report(engine)
    if before.get("application") is not None:
        for t in ("application", "application_file", "status_change", "project"):
            if before[t] != after[t]:
                raise RuntimeError(f"migration changed the number of rows in {t}: {before[t]} -> {after[t]}")
        if before.get("by_status") != after.get("by_status"):
            raise RuntimeError("migration changed application statuses")
    if after["without_owner"]:
        raise RuntimeError(f"{after['without_owner']} application(s) still have no owner")
    return {"before": before, "after": after}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="only print the report, change nothing")
    args = p.parse_args()
    from web import config
    from web.db import engine
    config.ensure_dirs()
    if args.check:
        print(json.dumps(report(engine), ensure_ascii=False, indent=2))
        return
    result = migrate(engine)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("OK: rows kept, statuses kept, every application has an owner, schema version",
          result["after"]["version"])


if __name__ == "__main__":
    main()
