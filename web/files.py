"""Saving uploaded files to data/uploads/<app_id>/ and validating them.

Validation mirrors the evaluation side (core.service.input_mode): only known image/video extensions, and either
one video or several photos, never mixed. SHA-256 is computed with core.service.file_sha256 (the same hash the
duplicate control and the simulator use).
"""
from pathlib import Path

from starlette.datastructures import UploadFile

from core.service import InputError, file_sha256, input_mode
from web import config

CHUNK = 1 << 20


class UploadRejected(Exception):
    """A problem the operator can fix: wrong type, mixed input, too large, empty."""


def check_mode(names: list[str]) -> str:
    """Return the input mode for these file names, or raise UploadRejected with a Ukrainian message."""
    if not names:
        raise UploadRejected("Додайте хоча б один файл.")
    for n in names:
        if Path(n).suffix.lower() not in config.ALLOWED_EXTS:
            raise UploadRejected(f"Непідтримуваний тип файлу: {n}. "
                                 f"Дозволені: {', '.join(sorted(e[1:] for e in config.ALLOWED_EXTS))}.")
    try:
        return input_mode([Path(n) for n in names])
    except InputError as e:
        msg = str(e)
        if "one video" in msg:
            raise UploadRejected("Одне відео або кілька фото, не разом.")
        raise UploadRejected(f"Неприйнятний набір файлів: {msg}")


def save_uploads(app_id: int, uploads: list[UploadFile]) -> list[dict]:
    """Save each upload under data/uploads/<app_id>/, enforcing the size limit; return file metadata dicts."""
    dest = config.UPLOADS_DIR / str(app_id)
    dest.mkdir(parents=True, exist_ok=True)
    limit = config.max_upload_mb() * 1024 * 1024
    saved: list[dict] = []
    for up in uploads:
        name = Path(up.filename).name
        target = dest / name
        size = 0
        with open(target, "wb") as out:
            up.file.seek(0)
            while True:
                chunk = up.file.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise UploadRejected(f"Файл {name} більший за {config.max_upload_mb()} МБ.")
                out.write(chunk)
        if size == 0:
            target.unlink(missing_ok=True)
            raise UploadRejected(f"Файл {name} порожній.")
        saved.append({"name": name, "path": str(target), "bytes": size, "sha256": file_sha256(target)})
    return saved
