# Test set (task 9.2)

`cases.csv` lists the cases; `input` is relative to the repository root and points outside it
(`../videos`, `../Dataset_CVAT`), because the files are too large for git.

| kind | count | what it is |
|---|---|---|
| generated_video | 7 | one Lyra-2 orbit per building from the paper's video corpus, only videos watched and approved by the team (2026-10-17): others had the camera going underground or invented walls |
| photo | 2 | single ground-level photos |
| photos | 1 | five frames of the download12_2 orbit saved as photos: the same building as a video case, so the two modes can be compared |

Limitations, to be stated at the defence:
- The generated videos are made from one real photo each; the other sides of the building are invented
  by the video model. They check that the pipeline works, not that the assessment is right.
- All source photos are in the segmentation model's training data, so the masks are better than they
  would be on new images.
- Real drone footage (task "Test data collection") is still to be added as `real_video` rows.

`expected_damage` / `expected_condition` are a draft from a visual review of each source photo and
must be confirmed by the team. Run everything with:

    uv run python -m tools.run_testset testset/cases.csv                       # free: cached answers or stubs
    uv run python -m tools.run_testset testset/cases.csv --gemini --name NAME  # paid requests

Each run is saved in `output/runs/<date-time>_<name>/` (see tools/run_testset.py).
