# Building-damage-estimation

Photos or a video of a damaged building in, a preliminary report out: damage category
(Methodology No. 144) and technical condition category (ДСТУ 9273:2024), building parameters,
list of works, and a restoration cost shown as a range, with PDF export. Screening and triage
only - it orders buildings for on-site inspection and does not replace it.

This is the `production` branch: the working product only. Every assessment is a new request to Gemini;
there is no answer cache, no stub answers, no simulator and no development data. Development happens on
`dev`, verified work goes to `main`, and `production` is `main` without the development tooling.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned in `.python-version`.

```bash
uv sync --extra ml      # dependencies, with torch for the segmentation model
cp .env.example .env    # then set GEMINI_API_KEY
uv run pytest           # no request is sent: tests use fakes in place of Gemini
```

## Model weights

The segmentation model is the DINOv2-Emb U-Net from Lysanets et al., *Applied Artificial
Intelligence* 40(1), 2026, e2685357. The weights (`dinov2_b2b_6class.pt`, 1.26 GB) are too large
for git: put the file into `weights/` (path set in `config.toml`). The ConvNeXt-L CLIP embedder
(~800 MB) is downloaded by `timm` from Hugging Face on the first run and cached.

On CPU one photo takes 25-60 s (it is tiled into 518 px crops); loading the model takes ~15 s.

## Run

```bash
scripts/run_production.sh            # http://localhost:8001; Ctrl+C stops the server and the worker
```

The script checks the key and the weights, then starts the web server and the background worker.
Applications, uploaded files, results and the mask cache are kept in `data_prod/`; prices in
`data/materials.db`. Every new application sends 2-4 Gemini requests (building parameters, then the
decision), and every reevaluation after the operator corrects the building parameters sends one more.
Each request is logged in `output/gemini_usage.csv`. If Gemini does not answer, the application goes to
"Збій" with a retry button; a partial report is never produced.

## The operator web system

- **Board** (`/board`): applications by status (Створено, Обробляється, Оброблено, Затверджено, Відхилено,
  Збій) with filters by category, condition, confidence, project, date, cost and title.
- **Application** (`/applications/<id>`): the summary, views with damage masks (full size on click), building
  parameters that can be corrected and recalculated, works and cost, the PDF report, approve or decline with
  a reason, the status history.
- **Duplicates**: an upload whose file is already in another application (by SHA-256) is held with a
  choice: decline it, merge it into the earlier application, or process it anyway.
- **Projects** (`/projects`): applications grouped by street or community, with the total cost.
- **Statistics** (`/statistics`): counts by status and category, processing time, failure rate.
- **Prices and materials** (`/materials`): current prices, a new price with the date it applies from (the
  old one stays in the history), new materials, labour rates.

## Building parameters

Gemini (gemini-3.8-flash) looks at the frame with the most facade, cropped to the building (no mask drawn,
so windows and floor lines stay clean; the next frames are tried if floors cannot be read), and returns the floor count, structure type, roof
type and, if floors cannot be read, a door, car or person with its box (fallback heights 2.1 / 1.5 /
1.7 m). Code turns the height into a scale using the facade in the mask, then width; depth is measured on
the narrowest view when at least three views show the building (the end wall), otherwise a typical 12 m
(`[geometry] typical_depth_m`, never more than the width), stated in the report as an assumption. A rough consequence class (ДБН В.1.2-14:2018, table 1) is estimated from the size.
Every detected value is marked as automatic and can be corrected; the pipeline is split into
`segment_case` (slow, once) and `evaluate` (fast), so a correction never re-runs the model.

## Decision layer

The language model (gemini-3.8-flash) receives the measurements and up to `[decision] max_images`
views (worst section, worst facade view, worst roof view first), cropped to the building with the
segmentation drawn over them (light fill and outlines, so the photo stays visible). The numbers are the
main evidence; the images show what the damage is. It returns fixed fields validated against a schema:
damage category I-III (Methodology No. 144, Додаток 3), technical condition 1-4 (ДСТУ 9273:2024),
a confidence and work type codes from `core/reference.py`. The prompt also gets the worst single
view, the share of damage in the lower / middle / upper third of the facade and the roof covering
category computed in code from ДСТУ 9273 table В.7.1. A malformed answer is retried. Quantities are
the damaged areas, computed by code. Confidence sets how far the categories can be trusted for
ordering inspections: confirmed, preliminary, insufficient data.

Rules enforced by code whatever the model answers: in category I a wall is holed only locally, so the share of
wall destroyed through (masonry, debris removal) is capped at 10% (`[decision] category_one_max_destroyed`);
category III gets no works and no cost ("restoration is not reasonable, demolition
recommended", Methodology No. 144); a roof seen only as a strip keeps its damage share, but no roof area or
roof cost is computed from it.

## Cost

`core/cost.py`: damaged area x (materials per m2 x price + labour per m2), widened into a range by
the scale error and the number of views. Prices come from a `PriceSource` chosen in `config.toml`
`[prices] source`:
- `db` (default): the materials database (`pricedb/`, epic 5), SQLite at `data/materials.db`, created and
  seeded on first use (or `uv run python scripts/init_db.py`). 14 work types (`core/reference.py`), 35
  materials with a bill of quantities per m2 of work, and labour rates per m2, each price with its source
  and date (`pricedb/seed_data.py`). Roof works exist for pitched and flat roofs; the code swaps them to
  match the detected roof type.
- `csv`: `resources/prices_sample/` - sample numbers with labour rates, not real prices.

Prices have dates and are never overwritten. `scripts/show_prices.py` prints what the source returns.

## Video

`core/video.py`: frames every second (ffmpeg), blurred ones dropped by variance of the Laplacian; the video is
split into K = 5 equal time spans (an orbit moves around the building, so the spans cover its sides), and in
each span two candidates are segmented quickly (one pass at 518 px, ~5 s on CPU); the one showing the
building best wins, a frame where the building is cut off on three or four sides loses. Picking the most
different frames (the first version) chose trees, walls at arm's length and neighbours' roofs instead.

## Limitations and known issues

- A preliminary visual assessment for ordering inspections, not a technical inspection: load-bearing
  structures inside the building cannot be seen in photos (Methodology No. 144 does not allow an inspection
  from photos alone).
- Only the walls seen are measured; the other sides are reported as not assessed. With one side seen, the
  depth is a typical 12 m, not measured.
- The roof area comes from the building's dimensions, not from the roof in the mask; a roof seen only as a
  strip is not priced.
- Broken windows are overcounted on buildings with glazed balconies: the segmentation sometimes marks balcony
  glazing as broken windows.
- Wall works depend on the language model's judgement of how much of the damaged facade is window openings
  and how much of the wall is destroyed through.
- Costs are rough: 14 work types, 35 materials, prices from public sources, a range that widens with fewer
  views.
- Duplicate control in the web system catches identical files only, not another photo of the same building.

## Structure

```
core/              the assessment
  service.py       Engine: files in, a result folder out (result.json, report.pdf, views/); reevaluate
  pipeline.py      segment_case (slow, once) + evaluate (fast)
  types.py         Case, FrameMetrics, BuildingParams, Decision, CostEstimate, Report; the six classes
  interfaces.py    replaceable components: SegmentationModel, BuildingParamsEstimator, DecisionLayer, PriceSource
  metrics.py       masks -> per-frame ratios -> combined ratios, worst view, damage by height
  geometry.py      ratios -> m2, uncertainty range
  building.py      facade size from the mask, scale, width, consequence class
  decision.py      work quantities, category rules and confidence levels (code, not the model)
  reference.py     both category scales, work types, roof rule, Ukrainian labels
  cost.py          cost calculation
  video.py         frame extraction, blur filter, view selection
  case.py          building a Case from photos or a video
  report_pdf.py    PDF report
  cache.py         mask cache (a file is not segmented twice), output.py, imageio.py, config.py
models/
  dinov2_unet.py, damage_seg.py   trained segmentation model (paper code, unchanged)
  gemini_client.py                shared Gemini call: schema validation, retry
  gemini_building.py              building parameters from a photo
  gemini_decision.py              categories and works
  price_source.py, csv_prices.py  price sources
pricedb/           materials and prices database (SQLite): materials, work types, labour rates, price history
web/               the operator web system (FastAPI, Jinja2, HTMX) and the background worker
scripts/           run_production.sh, init_db.py, show_prices.py
resources/         sample prices, fonts for the PDF
tests/             tests; tests/doubles.py holds the fakes used in place of the model and Gemini
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
| web/ui        | max_upload_mb                     | largest file the operator can upload |
| decision      | model, seed                       | Gemini model name; fixed seed with temperature 0 for repeatable answers |

API keys live in `.env`, never in the config.
