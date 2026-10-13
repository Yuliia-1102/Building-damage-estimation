"""Building a Case from what the user gave us (task 1.7)."""
from pathlib import Path

from core.types import Case, View

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def case_from_paths(case_id: str, paths: list[Path]) -> Case:
    """One photo or several; each photo is its own view."""
    images = sorted(p for p in map(Path, paths) if p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise ValueError(f"no images in case {case_id}")
    views = [View(view_id=i, image_path=p) for i, p in enumerate(images, start=1)]
    return Case(case_id=case_id, mode="photo" if len(views) == 1 else "photos", views=views)


def case_from_folder(folder: Path) -> Case:
    folder = Path(folder)
    if folder.is_file():
        return case_from_paths(folder.stem, [folder])
    return case_from_paths(folder.name, list(folder.iterdir()))
