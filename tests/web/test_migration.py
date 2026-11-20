"""Migration of the v1.0 training data set (tests/web/data/v1_sample.sql, made with the v1.0 code) to v2.0."""
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text

SAMPLE = Path(__file__).parent / "data" / "v1_sample.sql"


def _v1_db(tmp_path) -> Path:
    path = tmp_path / "v1.db"
    con = sqlite3.connect(path)
    con.executescript(SAMPLE.read_text(encoding="utf-8"))
    con.close()
    return path


def _rows(engine, sql):
    with engine.connect() as c:
        return [tuple(r) for r in c.execute(text(sql)).all()]


def test_v1_data_survive_the_migration(tmp_path):
    from web.migrate import migrate, report
    engine = create_engine(f"sqlite:///{_v1_db(tmp_path)}")
    assert report(engine)["version"] == 1
    keys = "SELECT id, title, status, created_at, queued_at, decided_at, decision_comment, cost_total, " \
           "duplicate_of_id, project_id FROM application ORDER BY id"
    apps_before = _rows(engine, keys)
    history_before = _rows(engine, "SELECT id, application_id, from_status, to_status, at FROM status_change")
    files_before = _rows(engine, "SELECT id, application_id, sha256 FROM application_file")

    result = migrate(engine)

    assert result["after"]["version"] == 2 and result["after"]["without_owner"] == 0
    assert _rows(engine, keys) == apps_before                     # ids, statuses, dates, decisions untouched
    assert _rows(engine, "SELECT id, application_id, from_status, to_status, at FROM status_change") == history_before
    assert _rows(engine, "SELECT id, application_id, sha256 FROM application_file") == files_before
    owners = _rows(engine, "SELECT DISTINCT u.username FROM application a JOIN app_user u ON u.id = a.owner_id")
    assert owners == [("legacy",)]                                 # old records need no new approval
    assert ("Approved",) in _rows(engine, "SELECT status FROM application")


def test_migration_runs_twice_without_changes(tmp_path):
    from web.migrate import migrate, report
    engine = create_engine(f"sqlite:///{_v1_db(tmp_path)}")
    migrate(engine)
    first = report(engine)
    migrate(engine)
    assert report(engine) == first
    assert _rows(engine, "SELECT COUNT(*) FROM app_user WHERE username = 'legacy'") == [(1,)]


def test_legacy_owner_cannot_sign_in(tmp_path):
    from sqlalchemy.orm import Session

    from web.auth import authenticate
    from web.migrate import migrate
    engine = create_engine(f"sqlite:///{_v1_db(tmp_path)}")
    migrate(engine)
    with Session(engine) as s:
        assert authenticate(s, "legacy", "") is None
        assert authenticate(s, "admin", "demo2026") is not None


def test_two_processes_migrating_at_once(tmp_path):
    """The server and the worker start together on a v1.0 database: both must come up (review on PR #5)."""
    import threading

    from web.migrate import migrate, report
    db = _v1_db(tmp_path)
    errors = []

    def start():
        try:
            migrate(create_engine(f"sqlite:///{db}"))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    after = report(create_engine(f"sqlite:///{db}"))
    assert after["version"] == 2 and after["without_owner"] == 0 and after["app_user"] == 4
