"""From a video to a few views of the building from different sides (epic 8).

  1. sample frames at a fixed interval                                  (task 8.1)
  2. drop blurred frames by variance of Laplacian                       (task 8.2)
  3. split the video into K equal time spans: a flight around the building moves on, so the spans cover
     its sides                                                          (task 8.4)
  4. in each span, segment a few candidate frames quickly and keep the one that shows the building best:
     most of the frame is building, and the building is not cut off on three or four sides (a wall at
     arm's length, a tree or debris filling the view)                   (task 8.3)

The first version picked the K frames least alike (greedy max-min on DINOv2 embeddings). On real orbits that
picks exactly the bad frames above, because they are the most different ones. Similarity to the median frame
did not work either: the damaged side is the rarest view of an orbit, so it looked "atypical" too.
max_min_select is kept for comparison.
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


def frame_quality(mask: np.ndarray) -> tuple[float, str]:
    """How well a (quick) mask shows the building: the share of the frame that is building. When the building
    touches three or four edges of the frame (seen from too close, or something in front of it), the score
    drops below 0.1 and favours the wider shot among such frames: 0.1 x (1 - share)."""
    building = mask > 0
    share = float(building.mean())
    if share == 0:
        return 0.0, "no building"
    rows, cols = np.flatnonzero(building.any(axis=1)), np.flatnonzero(building.any(axis=0))
    h, w = mask.shape
    edges = int(rows[0] == 0) + int(rows[-1] == h - 1) + int(cols[0] == 0) + int(cols[-1] == w - 1)
    if edges >= 3:
        return 0.1 * (1 - share), f"building cut off on {edges} sides"
    return share, ""


def span_candidates(sharp: list[int], k: int, n_frames: int, per_span: int, extra: int = 0) -> list[list[int]]:
    """For each of k equal time spans: per_span sharp frames spread inside it (away from its edges, so views from
    neighbouring spans do not end up next to each other), then up to `extra` spare frames nearest its middle."""
    spans = []
    for span in range(k):
        lo, hi = span * n_frames / k, (span + 1) * n_frames / k
        inside = [i for i in sharp if lo <= i < hi]
        if not inside:
            continue
        targets = [lo + (hi - lo) * (j + 1) / (per_span + 1) for j in range(per_span)]
        picks = list(dict.fromkeys(min(inside, key=lambda i: abs(i - t)) for t in targets))
        spare = sorted((i for i in inside if i not in picks), key=lambda i: abs(i - (lo + hi) / 2))
        spans.append(picks + spare[:extra])
    return spans


def select_views(frames: list[Path], embedder=None, k: int | None = None,
                 quick_segmenter=None) -> tuple[list[Path], dict]:
    """K views spread over the video, in the order they appear, plus a log of what was dropped and why.
    Without quick_segmenter the middle candidate of each span is taken (no quality check)."""
    k = k or config.get("video", "views_k")
    blur_t = config.get("video", "blur_threshold")
    per_span = config.get("video", "candidates_per_span")

    images = [np.asarray(Image.open(f).convert("RGB")) for f in frames]
    scores = [sharpness(im) for im in images]
    sharp = [i for i, s in enumerate(scores) if s >= blur_t]
    if not sharp:                     # a uniformly soft video: keep the sharpest half rather than nothing
        sharp = sorted(range(len(frames)), key=lambda i: -scores[i])[:max(1, len(frames) // 2)]
        log.warning("no frame above the blur threshold %.0f; kept the sharpest half", blur_t)

    extra = config.get("video", "extra_candidates")
    picked, rejected, checked = [], {}, 0

    def rate(i):
        nonlocal checked
        q, reason = frame_quality(quick_segmenter.predict_path(frames[i]))
        checked += 1
        if reason:
            rejected[frames[i].name] = reason
        return q, i

    for candidates in span_candidates(sharp, k, len(frames), per_span, extra):
        first = candidates[:per_span]
        if quick_segmenter is None:
            picked.append(first[len(first) // 2])
            continue
        rated = [rate(i) for i in first]
        # every candidate shows the building cut off or not at all: look at a few more frames of this span
        for i in candidates[per_span:]:
            if max(rated)[0] >= 0.1:
                break
            rated.append(rate(i))
        best_q, best = max(rated)
        if best_q > 0:
            picked.append(best)
    picked.sort()
    info = {"extracted": len(frames), "blurred": len(frames) - len(sharp), "checked": checked,
            "rejected": rejected, "selected": len(picked),
            "sharpness": {frames[i].name: round(scores[i], 1) for i in range(len(frames))}}
    log.info("video views: %s", {k: v for k, v in info.items() if k != "sharpness"})
    return [frames[i] for i in picked], info
