# Test set (task 9.2)

`cases.csv` lists the cases; `input` is relative to the repository root and points outside it
(`../videos`, `../Dataset_CVAT`), because the files are too large for git.

| kind | count | what it is |
|---|---|---|
| generated_video | 11 | one Lyra-2 orbit per building from the paper's video corpus, only sequences that passed its quality check (rotation error ≤ 5.60°) |
| photo | 1 | a single ground-level photo |
| photos | 1 | four photos of one building |

Limitations, to be stated at the defence:
- The generated videos are made from one real photo each; the other sides of the building are invented
  by the video model. They check that the pipeline works, not that the assessment is right.
- All source photos are in the segmentation model's training data, so the masks are better than they
  would be on new images.
- Real drone footage (task "Test data collection") is still to be added as `real_video` rows.

`expected_damage` / `expected_condition` are a draft from a visual review of each source photo and
must be confirmed by the team. Run everything with:

    uv run python -m tools.run_testset testset/cases.csv --out output/testset.csv
    uv run python -m tools.run_testset testset/cases.csv --repeat 3 --no-decision-cache --out output/consistency.csv
