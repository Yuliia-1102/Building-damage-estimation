import numpy as np
from PIL import Image

from core.case import case_from_folder
from core.pipeline import assess
from models.stub import StubBuildingParams, StubSegmenter


def test_assess_runs_end_to_end_with_stubs(tmp_path):
    for i, size in enumerate([(640, 480), (480, 640), (800, 300)]):
        Image.fromarray(np.zeros((size[1], size[0], 3), dtype=np.uint8)).save(tmp_path / f"{i}.png")
    (tmp_path / "broken.jpg").write_bytes(b"not an image")

    report = assess(case_from_folder(tmp_path), StubSegmenter(), building_estimator=StubBuildingParams())

    assert report.mode == "photos"
    assert report.views_assessed == 3
    assert len(report.skipped_frames) == 1
    assert report.ratios.damaged_facade is not None
    assert report.areas is not None and report.areas.damaged_facade_m2 > 0
