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


def case_from_video(video: Path, work_dir: Path, quick_segmenter=None) -> tuple[Case, dict]:
    """Frames are extracted into work_dir; one good view per time span becomes a view (task 8.5).
    quick_segmenter (models.dinov2_unet.QuickSegmenter, cached) checks the candidates; see core/video.py."""
    from core.video import extract_frames, select_views
    video = Path(video)
    frames = extract_frames(video, Path(work_dir) / video.stem / "frames")
    picked, info = select_views(frames, quick_segmenter=quick_segmenter)
    views = [View(view_id=i, image_path=p) for i, p in enumerate(picked, start=1)]
    return Case(case_id=video.stem, mode="video", views=views), info


def case_from_folder(folder: Path) -> Case:
    folder = Path(folder)
    if folder.is_file():
        return case_from_paths(folder.stem, [folder])
    return case_from_paths(folder.name, list(folder.iterdir()))
