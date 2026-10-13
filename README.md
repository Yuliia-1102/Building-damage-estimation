# Building-damage-estimation

Photos or a video of a damaged building in, a preliminary report out: condition category,
list of works, and a restoration cost shown as a range. Screening and triage only - not an
engineering assessment.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned in `.python-version`.

```bash
uv sync                 # core dependencies + pytest
uv sync --extra ml      # + torch, needed for the real segmentation model
cp .env.example .env    # then fill in the API key
uv run pytest
```

## Run

```bash
# a folder of photos = one case; a single image also works
uv run python cli.py data/cases/<case>            # stub segmenter
uv run python cli.py data/cases/<case> --json

# run on ground-truth masks from the CVAT dataset instead of the model
uv run python -m tools.cvat ../Dataset_CVAT/annotations.xml data/cvat_masks
uv run python cli.py data/cases/<case> --masks data/cvat_masks
```

## Structure

```
core/            all logic; the UI and the CLI only call assess()
  types.py       Case, FrameMetrics, BuildingParams, Report ... and the six classes (Cls)
  interfaces.py  replaceable components: SegmentationModel, BuildingParamsEstimator,
                 DecisionLayer, PriceSource
  pipeline.py    assess(case) -> Report
  metrics.py     masks -> per-frame ratios -> combined ratios (division of sums)
  geometry.py    ratios -> m2, uncertainty range
  imageio.py     loading with EXIF rotation, mask overlay and colour legend
  case.py        building a Case from files
  config.py      reads config.toml
models/          implementations of the interfaces (stub.py: stubs for tests and development)
tools/cvat.py    CVAT XML export -> 6-class masks
ui/              Streamlit app
tests/
data/            local data, not in git (cases/, cvat_masks/)
config.toml      every threshold and coefficient, with where it came from
```

## Segmentation classes

| id | class          | CVAT label    |
|----|----------------|---------------|
| 0  | background     | Other         |
| 1  | facade         | Building      |
| 2  | roof           | Roof          |
| 3  | damaged facade | Damage        |
| 4  | broken window  | Broken Window |
| 5  | damaged roof   | Damaged roof  |

Visible facade = 1 + 3 + 4, visible roof = 2 + 5.

## Configuration

`config.toml` holds every tunable number; nothing is hardcoded in the code.

| section       | parameter                         | meaning |
|---------------|-----------------------------------|---------|
| suitability   | min_facade_share, min_roof_share  | a frame counts for a surface only if it takes at least this share of the frame |
| geometry      | default_floor_height_m            | height of one floor when not detected |
| geometry      | roof_shape_coef_*                 | roof area = width x depth x coefficient |
| uncertainty   | scale_error, coverage_coef        | range half-width = scale_error + coverage_coef / views |
| confidence    | high, low                         | escalation boundaries for the decision layer |
| video         | frame_interval_s, blur_threshold, views_k | frame extraction and view selection |
| prices        | max_candidates                    | cap on catalogue items passed to the model |

API keys live in `.env`, never in the config.
