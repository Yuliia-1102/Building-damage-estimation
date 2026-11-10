"""SQLAlchemy engine and session for the web database.

One SQLite file (web/config.DB_PATH) is shared by the web server and the worker process, so it runs in WAL
mode with a busy timeout: both processes can read and write without "database is locked". Sessions are short;
open one per request or per worker step with `session_scope()`.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from web import config


class Base(DeclarativeBase):
    pass


engine = create_engine(
    config.DB_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")      # readers and writers do not block each other
    cur.execute("PRAGMA busy_timeout=30000")    # wait up to 30 s for a lock instead of failing
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create the database file and all tables if they do not exist. Safe to call on every startup."""
    config.ensure_dirs()
    from web import models  # noqa: F401  (registers the tables on Base)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope():
    """A session that commits on success and rolls back on error."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
