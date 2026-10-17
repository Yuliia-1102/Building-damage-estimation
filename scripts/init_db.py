"""Create the materials database and load the base data (epic 5).

    python scripts/init_db.py

Path comes from config.toml [paths] materials_db. Safe to run repeatedly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config  # noqa: E402
from pricedb import create_db, load_seed, session_factory, sqlite_url  # noqa: E402

if __name__ == "__main__":
    db_path = config.path("materials_db")
    engine = create_db(sqlite_url(db_path))
    with session_factory(engine)() as session:
        load_seed(session)
    print(f"Materials database ready: {db_path}")
