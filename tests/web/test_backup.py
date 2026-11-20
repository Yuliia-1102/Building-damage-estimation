"""Backup and restore: the data after a restore are the data at the time of the backup."""
import shutil
import sqlite3

import pytest
from sqlalchemy import func, select

from web.models import Application


@pytest.fixture
def materials(tmp_path, monkeypatch):
    """Never touch the real data/materials.db in tests."""
    from web import backup
    path = tmp_path / "materials.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(backup, "_materials_db", lambda: path)
    return path


def test_restore_brings_back_the_backup(client, create, pump, db, tmp_path, materials):
    from web import backup, config
    a1 = create("photo_single", "до бекапу")
    pump()
    archive = backup.create(tmp_path / "backups")

    # "Accident" after the backup: a new application and lost uploaded files.
    create("download10", "після бекапу")
    shutil.rmtree(config.UPLOADS_DIR / str(a1))
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Application)) == 2

    result = backup.restore(archive)

    assert result["problems"] == []
    with db() as s:
        titles = [a.title for a in s.scalars(select(Application)).all()]
    assert titles == ["до бекапу"]
    assert (config.UPLOADS_DIR / str(a1)).exists()
    assert client.get(f"/applications/{a1}").status_code == 200


def test_verify_reports_a_difference(client, create, db, tmp_path, materials):
    import json
    import zipfile

    from web import backup
    create("photo_single", "одна")
    archive = backup.create(tmp_path / "backups")
    create("download10", "друга")
    manifest = json.loads(zipfile.ZipFile(archive).read("manifest.json"))
    assert any(p.startswith("application:") for p in backup.verify(manifest))


def test_paths_are_moved_to_the_new_data_folder(tmp_path):
    from web import backup
    db = tmp_path / "web.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE application_file (path TEXT)")
        c.execute("CREATE TABLE application (result_dir TEXT)")
        c.execute("INSERT INTO application_file VALUES ('/old/data/uploads/1/a.jpg')")
        c.execute("INSERT INTO application VALUES ('/old/data/results/1')")
    assert backup._rewrite_paths(db, "/old/data", "/new/place") == 2
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT path FROM application_file").fetchone()[0] == "/new/place/uploads/1/a.jpg"


def test_damaged_archive_changes_nothing(client, create, pump, db, tmp_path, materials):
    """A half-downloaded archive is refused before the current data are deleted (review on PR #6)."""
    from web import backup, config
    aid = create("photo_single", "живі дані")
    pump()
    archive = backup.create(tmp_path / "backups")
    # The archive still opens (its index is intact), but the bytes of one file inside are spoiled.
    import zipfile
    data = bytearray(archive.read_bytes())
    with zipfile.ZipFile(archive) as z:
        info = z.getinfo("web.db")
    start = info.header_offset + 30 + len(info.filename) + len(info.extra)
    for i in range(start + 10, start + 60):
        data[i] ^= 0xFF
    damaged = tmp_path / "damaged.zip"
    damaged.write_bytes(bytes(data))

    with pytest.raises(backup.BadArchive):
        backup.restore(damaged)

    assert (config.UPLOADS_DIR / str(aid)).exists()
    with db() as s:
        assert [a.title for a in s.scalars(select(Application)).all()] == ["живі дані"]
