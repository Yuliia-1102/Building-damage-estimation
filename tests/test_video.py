import numpy as np
from PIL import Image, ImageFilter

from core.video import drop_near_duplicates, max_min_select, sharpness


def test_blurred_frame_scores_lower():
    rng = np.random.default_rng(0)
    sharp = (rng.random((120, 160, 3)) * 255).astype(np.uint8)
    blurred = np.asarray(Image.fromarray(sharp).filter(ImageFilter.GaussianBlur(4)))
    assert sharpness(sharp) > 10 * sharpness(blurred)


def test_max_min_picks_the_distinct_directions():
    # three clusters of nearly identical frames: selection takes one from each
    e = np.array([[1, 0, 0], [0.99, 0.05, 0], [0, 1, 0], [0.05, 0.99, 0], [0, 0, 1], [0, 0.05, 0.99]], float)
    picked = max_min_select(e, k=3, first=0)
    assert {p // 2 for p in picked} == {0, 1, 2}


def test_near_duplicates_dropped():
    e = np.array([[1, 0], [0.999, 0.01], [0, 1]], float)
    assert drop_near_duplicates(e, threshold=0.97) == [0, 2]


def test_candidates_cover_every_time_span():
    from core.video import span_candidates
    spans = span_candidates(list(range(40)), k=5, n_frames=40, per_span=2)
    assert len(spans) == 5
    assert all(len(c) == 2 for c in spans)
    assert all(8 * s < c[0] < c[1] < 8 * (s + 1) for s, c in enumerate(spans))   # away from span edges


def test_frame_quality_penalises_a_cut_off_building():
    from core.video import frame_quality
    whole = np.zeros((100, 100), np.uint8)
    whole[20:80, 20:80] = 1
    close_up = np.ones((100, 100), np.uint8)
    close_up[:, :10] = 0
    assert frame_quality(whole)[0] > frame_quality(close_up)[0]
    assert "3 sides" in frame_quality(close_up)[1]
    assert frame_quality(np.zeros((10, 10), np.uint8)) == (0.0, "no building")
