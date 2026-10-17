# Building-damage-estimation

Photos or a video of a damaged building in, a preliminary report out: damage category
(Methodology No. 144) and technical condition category (ДСТУ 9273:2024), building parameters,
list of works, and a restoration cost shown as a range, with PDF export. Screening and triage
only - it orders buildings for on-site inspection and does not replace it.

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

## Run the interface

```bash
uv run streamlit run ui/app.py
```

Pick the input mode (one photo, several photos, a video), upload, press «Оцінити». Without
`GEMINI_API_KEY` in `.env` the app runs in demo mode with fixed building parameters and decision.

## Run from the command line

```bash
uv run python cli.py path/to/video.mp4            # a video: the 5 most different sharp frames are used
uv run python cli.py data/cases/<case> --floors 6 # correct the floor count, recalculated without re-segmenting
uv run python cli.py data/cases/<case> --save output/<case>   # masks and overlays per view
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

## Building parameters

Gemini looks at the frame with the most facade and returns the floor count, structure type, roof
type and, if floors cannot be read, a door, car or person with its box (fallback heights 2.1 / 1.5 /
1.7 m). Code turns the height into a scale using the facade in the mask, then width; depth is assumed
equal to width. A rough consequence class (ДБН В.1.2-14:2018, table 1) is estimated from the size.
Every detected value is marked as automatic and can be corrected; the pipeline is split into
`segment_case` (slow, once) and `evaluate` (fast), so a correction never re-runs the model.

## Decision layer

The language model receives only numbers and returns fixed fields validated against a schema:
damage category I-III (Methodology No. 144, Додаток 3), technical condition 1-4 (ДСТУ 9273:2024),
a confidence and work type codes from `core/reference.py`. The prompt also gets the worst single
view, the share of damage in the lower / middle / upper third of the facade and the roof covering
category computed in code from ДСТУ 9273 table В.7.1. A malformed answer is retried. Quantities are
the damaged areas, computed by code. Confidence sets how far the categories can be trusted for
ordering inspections: confirmed, preliminary, insufficient data.

## Cost

`core/cost.py`: damaged area x (materials per m2 x price + labour per m2), widened into a range by
the scale error and the number of views. Prices come from a `PriceSource`; until the materials
database is connected it is `models/csv_prices.py` over `resources/prices_sample/` - sample numbers,
not real prices, and the report says so. Prices have dates and are never overwritten.

## Video

`core/video.py`: frames every second (ffmpeg), blurred ones dropped by variance of the Laplacian,
near-duplicates dropped, then DINOv2 embeddings and greedy max-min selection of K = 5 views.

## Test set

See `testset/README.md`. One command runs every case and writes one table; a second checks that
repeated runs give the same categories:

```bash
uv run python -m tools.run_testset testset/cases.csv --out output/testset.csv
uv run python -m tools.run_testset testset/cases.csv --repeat 3 --no-decision-cache --out output/consistency.csv
uv run python -m tools.consistency output/consistency.csv
```

## Structure

```
core/              all logic; the UI and the CLI only call it
  pipeline.py      segment_case (slow, once) + evaluate (fast) = assess(case) -> Report
  types.py         Case, FrameMetrics, BuildingParams, Decision, CostEstimate, Report; the six classes
  interfaces.py    replaceable components: SegmentationModel, BuildingParamsEstimator, DecisionLayer, PriceSource
  metrics.py       masks -> per-frame ratios -> combined ratios, worst view, damage by height
  geometry.py      ratios -> m2, uncertainty range
  building.py      facade size from the mask, scale, width, consequence class
  decision.py      work quantities and confidence levels (code, not the model)
  reference.py     both category scales, work types, roof rule, Ukrainian labels
  cost.py          cost calculation
  video.py         frame extraction, blur filter, view selection
  case.py          building a Case from photos or a video
  report_pdf.py    PDF export
  cache.py, output.py, imageio.py, config.py
models/            implementations of the interfaces
  dinov2_unet.py, damage_seg.py   trained segmentation model (paper code, unchanged)
  gemini_client.py                shared Gemini call: schema, retry, cache
  gemini_building.py              building parameters from a photo
  gemini_decision.py              categories and works from the numbers
  csv_prices.py                   price source over CSV, with history and admin functions
  dino_embedder.py                frame embeddings for video
  stub.py                         stand-ins for tests and demo mode
ui/app.py          Streamlit app
tools/             cvat.py (dataset -> masks), run_testset.py, consistency.py
testset/           test cases and expectations
resources/         sample prices, fonts for the PDF
tests/
config.toml        every threshold and coefficient, with where it came from
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
