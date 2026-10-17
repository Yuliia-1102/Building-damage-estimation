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
