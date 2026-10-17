"""Database creation and connection (epic 5.1)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, DamageClass

# The three damaged segmentation classes (Cls 3/4/5) that have a repair cost.
# `code` is the link to segmentation output and to core.reference.
DAMAGE_CLASSES: list[tuple[str, str]] = [
    ("damaged_facade", "Damaged facade"),
    ("broken_window", "Broken window"),
    ("damaged_roof", "Damaged roof"),
]


def _enable_sqlite_foreign_keys(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.close()


def get_engine(db_url: str) -> Engine:
    engine = create_engine(db_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def sqlite_url(path: str | Path) -> str:
    return f"sqlite:///{Path(path).resolve()}"


def create_db(db_url: str) -> Engine:
    """Create tables and the damage-class rows. Safe to run repeatedly."""
    if db_url.startswith("sqlite:///"):
        Path(db_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        existing = set(session.scalars(select(DamageClass.code)))
        for code, name in DAMAGE_CLASSES:
            if code not in existing:
                session.add(DamageClass(code=code, name=name))
        session.commit()
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def open_db(path: str | Path) -> sessionmaker[Session]:
    """Sessions for the database at `path`. Creates missing tables and adds missing seed rows, so a database
    made by an older version gets the new tables and data; rows edited by the admin are never overwritten."""
    from .seed import load_seed
    engine = create_db(sqlite_url(path))
    with session_factory(engine)() as session:
        load_seed(session)
    return session_factory(engine)
