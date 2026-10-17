"""From a video to a few views that differ as much as possible (epic 8).

No assumptions about the flight path, speed, orbit completeness or building shape (plan.txt, section 4):
  1. sample frames at a fixed interval            (task 8.1)
  2. drop blurred frames by variance of Laplacian (task 8.2)
  3. embed the rest and drop near-duplicates      (task 8.3)
  4. greedy max-min: K frames least alike         (task 8.4)
"""
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from core import config

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def extract_frames(video: Path, out_dir: Path, interval_s: float | None = None) -> list[Path]:
    """One JPEG every interval_s seconds, via ffmpeg."""
    interval_s = interval_s or config.get("video", "frame_interval_s")
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=1/{interval_s}", "-q:v", "2",
           str(out_dir / "frame_%04d.jpg")]
    subprocess.run(cmd, check=True)
    frames = sorted(out_dir.glob("frame_*.jpg"))
    log.info("extracted %d frames from %s", len(frames), Path(video).name)
    return frames


def sharpness(image: np.ndarray) -> float:
    """Variance of the Laplacian of the grey image: low for blurred frames."""
    g = image.astype(np.float32).mean(axis=2) if image.ndim == 3 else image.astype(np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def max_min_select(embeddings: np.ndarray, k: int, first: int = 0) -> list[int]:
    """Greedy farthest-point selection on cosine distance: each next frame is the one whose nearest
    already-selected frame is farthest away."""
    e = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    chosen = [first]
    nearest = 1 - e @ e[first]
    while len(chosen) < min(k, len(e)):
        nxt = int(np.argmax(nearest))
        if nearest[nxt] <= 0:
            break
        chosen.append(nxt)
        nearest = np.minimum(nearest, 1 - e @ e[nxt])
    return chosen


def drop_near_duplicates(embeddings: np.ndarray, threshold: float) -> list[int]:
    """Indices to keep: a frame is dropped if its cosine similarity to a kept earlier frame is above threshold."""
    e = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    kept = []
    for i in range(len(e)):
        if all(float(e[i] @ e[j]) < threshold for j in kept):
            kept.append(i)
    return kept


def select_views(frames: list[Path], embedder, k: int | None = None) -> tuple[list[Path], dict]:
    """The K most different sharp frames, in the order they appear in the video, plus a log of what was dropped."""
    k = k or config.get("video", "views_k")
    blur_t = config.get("video", "blur_threshold")
    dup_t = config.get("video", "duplicate_similarity")

    images = [np.asarray(Image.open(f).convert("RGB")) for f in frames]
    scores = [sharpness(im) for im in images]
    sharp = [i for i, s in enumerate(scores) if s >= blur_t]
    if not sharp:                     # a uniformly soft video: keep the sharpest half rather than nothing
        sharp = sorted(range(len(frames)), key=lambda i: -scores[i])[:max(1, len(frames) // 2)]
        log.warning("no frame above the blur threshold %.0f; kept the sharpest half", blur_t)

    emb = embedder.embed([images[i] for i in sharp])
    unique = [sharp[i] for i in drop_near_duplicates(emb, dup_t)]
    emb_unique = emb[[sharp.index(i) for i in unique]]

    first = int(np.argmax([scores[i] for i in unique]))   # start from the sharpest frame
    picked = sorted(unique[j] for j in max_min_select(emb_unique, k, first))
    info = {"extracted": len(frames), "blurred": len(frames) - len(sharp),
            "near_duplicates": len(sharp) - len(unique), "selected": len(picked),
            "sharpness": {frames[i].name: round(scores[i], 1) for i in range(len(frames))}}
    log.info("video views: %s", {k: v for k, v in info.items() if k != "sharpness"})
    return [frames[i] for i in picked], info
