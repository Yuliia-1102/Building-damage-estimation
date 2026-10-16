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

## Model weights

The segmentation model is the DINOv2-Emb U-Net from Lysanets et al., *Applied Artificial
Intelligence* 40(1), 2026, e2685357. The weights (`dinov2_b2b_6class.pt`, 1.26 GB) are too large
for git: put the file into `weights/` (path set in `config.toml`). The ConvNeXt-L CLIP embedder
(~800 MB) is downloaded by `timm` from Hugging Face on the first run and cached.

On CPU one photo takes 25-60 s (it is tiled into 518 px crops); loading the model takes ~15 s.

## Run

```bash
# a folder of photos = one case; a single image also works
uv run python cli.py data/cases/<case>            # trained model
uv run python cli.py data/cases/<case> --stub     # fake masks, no weights needed
uv run python cli.py data/cases/<case> --gemini   # real decision layer, needs GEMINI_API_KEY in .env
uv run python cli.py data/cases/<case> --json
uv run python cli.py data/cases/<case> --clear-cache   # drop cached masks and model answers

# run on ground-truth masks from the CVAT dataset instead of the model
uv run python -m tools.cvat ../Dataset_CVAT/annotations.xml data/cvat_masks
uv run python cli.py data/cases/<case> --masks data/cvat_masks
```

## Cache

Masks are cached in `cache/masks/` by the content hash of the photo, and decision-layer answers in
`cache/decisions/` by the hash of the prompt. A repeated run costs well under a second instead of
~40 s per photo. `--no-cache` bypasses it, `--clear-cache` deletes it.

## Decision layer

The language model receives only numbers (damage ratios, areas, floor count) and returns three
fixed fields, validated against a schema: condition category 1-4 (ДСТУ-Н Б В.1.2-18:2016), a
confidence, and work type codes from `core/reference.py`. A malformed answer is retried. The
quantity of each work is the damaged area of its surface, computed by code, never by the model.
Confidence decides what the report shows: the category, the category flagged for an engineer,
or no classification (`[confidence]` in the config).

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
  cache.py       on-disk cache for masks and model answers
  decision.py    work quantities and confidence escalation (code, not the model)
  reference.py   condition categories and work types the model chooses from
  config.py      reads config.toml
models/          implementations of the interfaces
  dinov2_unet.py trained segmentation model behind SegmentationModel
  damage_seg.py  the model itself, copied unchanged from the paper code
  gemini_decision.py  decision layer on the Gemini API: prompt, schema, retry
  stub.py        stubs for tests and development
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
| decision      | model, seed                       | Gemini model name; fixed seed with temperature 0 for repeatable answers |

API keys live in `.env`, never in the config.
