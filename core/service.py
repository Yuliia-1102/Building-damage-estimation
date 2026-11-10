"""Processing entry point for the operator web system (stage 3): uploaded files in, a saved result folder out.

    from core.service import get_engine
    engine = get_engine()                     # real model, or the simulator (DAMAGE_ENGINE=simulator)
    summary = engine.process([Path("a.jpg"), Path("b.jpg")], out_dir=Path("data/results/42"), case_id="42")

No Streamlit and no web framework here: a background worker calls process() and keeps the folder path.
The folder is self-contained (format: docs/web_system.md, section 4):
  result.json            the summary for lists and cards, file references and the full report
  report.pdf             the report for download
  views/view<N>.jpg      the view image (for video: the frame the system picked)
  views/view<N>_overlay.jpg   the image with the damage masks drawn over it, for display
  views/view<N>_mask.png      class per pixel (core.types.Cls), main building only
  views/view<N>_other.png     other buildings in the frame (255), not assessed

reevaluate() re-runs only the cheap part (areas, decision, cost) with building parameters the operator
corrected, from the saved folder, and rewrites it; segmentation is not repeated.

Language model answers: DAMAGE_LLM_MODE = "offline" (default: cached answers, stubs otherwise, never paid),
"gemini" (paid requests, needs GEMINI_API_KEY) or "claude" (development bridge, models/claude_bridge.py).
"""
import copy
import dataclasses
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from core import config
from core.types import (BuildingParams, CombinedRatios, CostEstimate, CostLine, DamagedAreas, Decision,
                        FacadeState, FrameMetrics, Report, WorkItem)

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

Progress = Callable[[float, str], None]   # (share done 0..1, what is happening, in Ukrainian)


class InputError(ValueError):
    """The uploaded files cannot be processed (wrong type, empty, a video mixed with photos)."""


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_mode(paths: list[Path]) -> str:
    """'photo' | 'photos' | 'video'. Raises InputError for anything else."""
    if not paths:
        raise InputError("no files")
    kinds = {"video" if p.suffix.lower() in VIDEO_EXTS else "image" if p.suffix.lower() in IMAGE_EXTS else "other"
             for p in paths}
    if "other" in kinds:
        raise InputError("unsupported file type: " + ", ".join(p.name for p in paths
                                                              if p.suffix.lower() not in IMAGE_EXTS | VIDEO_EXTS))
    if "video" in kinds:
        if len(paths) > 1:
            raise InputError("one video per case, without photos")
        return "video"
    return "photo" if len(paths) == 1 else "photos"


def describe_inputs(paths: list[Path]) -> list[dict]:
    return [{"name": p.name, "sha256": file_sha256(p), "bytes": p.stat().st_size} for p in paths]


# ---------- the real engine ----------

class RecordedDecision:
    """Keeps the recorded categories and chosen works; quantities follow the corrected areas (re-evaluation)."""

    def __init__(self, decision):
        self.recorded = decision

    def decide(self, ratios, areas, building, views=None):
        from core.decision import apply_category_rules, match_roof_type, works_with_quantities
        d = self.recorded
        if d is None:
            return None
        d.facade = apply_category_rules(d.damage_category, d.facade)
        codes = match_roof_type([w.work_type for w in d.works], building and building.roof_type)
        d.works = works_with_quantities(codes, areas, d.facade, building, facade_damaged=bool(ratios.damaged_facade))
        return d


def _delay() -> tuple[float, float]:
    raw = os.environ.get("DAMAGE_SIM_DELAY", "3-8")
    lo, _, hi = raw.partition("-")
    return float(lo), float(hi or lo)


class Engine:
    """Loads the models once (a worker keeps one Engine for its lifetime); process() is then 10-60 s per view."""

    name = "real"

    def __init__(self, llm: str | None = None):
        self.llm = llm or os.environ.get("DAMAGE_LLM_MODE", "offline")
        if self.llm not in ("offline", "gemini", "claude"):
            raise ValueError(f"DAMAGE_LLM_MODE must be offline, gemini or claude, not {self.llm!r}")
        weights = config.path("weights")
        if weights.exists():
            from core.cache import CachedSegmenter, quick_segmenter
            from models.dinov2_unet import DinoV2Segmenter
            self.segmenter = CachedSegmenter(DinoV2Segmenter(), model_id=weights.stem)
            self.quick = quick_segmenter(self.segmenter)
            self.segmentation_source = "model"
        else:
            from models.stub import StubSegmenter
            log.warning("no weights at %s: stub masks", weights)
            self.segmenter, self.quick, self.segmentation_source = StubSegmenter(), None, "stub"
        if self.llm == "offline":
            from models.offline import CachedOrStubBuilding, CachedOrStubDecision
            self.building, self.decision = CachedOrStubBuilding(), CachedOrStubDecision()
        else:
            if self.llm == "claude":
                os.environ.setdefault("DAMAGE_LLM", "claude-sonnet-5-5")
            from models.gemini_building import GeminiBuildingEstimator
            from models.gemini_decision import GeminiDecisionLayer
            self.building, self.decision = GeminiBuildingEstimator(), GeminiDecisionLayer()
        from models.price_source import default_price_source
        self.prices = default_price_source()

    def _source(self, layer) -> str:
        if hasattr(layer, "last_source"):
            return layer.last_source or ""
        if self.llm == "claude":
            return "claude-dev"
        return "cache" if layer.llm.last_from_cache else "gemini"

    def process(self, inputs: list[Path], out_dir: Path, case_id: str | None = None,
                progress: Progress | None = None) -> dict:
        """Assess the uploaded files and save the result folder. Returns the result.json content.
        Raises InputError for bad input; any other exception means the processing failed."""
        from core.case import case_from_paths, case_from_video
        from core.pipeline import evaluate, segment_case

        inputs = [Path(p) for p in inputs]
        mode = input_mode(inputs)
        case_id = case_id or inputs[0].stem + (f"+{len(inputs) - 1}" if len(inputs) > 1 else "")
        progress = progress or (lambda share, text: None)
        started = time.time()
        with tempfile.TemporaryDirectory() as work:
            video_info = None
            if mode == "video":
                progress(0.02, "Нарізаємо відео і відбираємо кадри")
                case, video_info = case_from_video(inputs[0], Path(work), self.quick)
                case.case_id = case_id
            else:
                case = case_from_paths(case_id, inputs)
            if not case.views:
                raise InputError("no usable frames in the video")

            def seg_progress(done, total, _):
                progress(0.1 + 0.7 * done / max(total, 1), f"Сегментація: вид {min(done + 1, total)} з {total}")

            seg = segment_case(case, self.segmenter, seg_progress)
            progress(0.82, "Параметри будівлі, категорії, роботи і вартість")
            report = evaluate(seg, building_estimator=self.building, decision_layer=self.decision,
                              price_source=self.prices)
        sources = {"segmentation": self.segmentation_source,
                   "building": self._source(self.building) if report.building else "",
                   "decision": self._source(self.decision) if report.decision else ""}
        extra = {"video": video_info, "seconds": round(time.time() - started, 1)}
        progress(0.95, "Зберігаємо результат і PDF")
        data = save_result(seg, report, Path(out_dir), describe_inputs(inputs), sources, extra)
        progress(1.0, "Готово")
        return data

    def reevaluate(self, result_dir: Path, changes: dict) -> dict:
        """Building parameters corrected by the operator (floors, floor_height_m, width_m, depth_m, roof_type,
        structure_type): areas, decision and cost are recalculated, the folder is rewritten."""
        from core.building import best_frame_for_floors
        from core.pipeline import evaluate
        from models.gemini_building import recompute

        result_dir = Path(result_dir)
        seg, report, data = load_result(result_dir)
        if report.building is None:
            raise InputError("the result has no building parameters to correct")
        allowed = {"floors", "floor_height_m", "width_m", "depth_m", "roof_type", "structure_type"}
        unknown = set(changes) - allowed
        if unknown:
            raise InputError("cannot change: " + ", ".join(sorted(unknown)))
        building = copy.deepcopy(report.building)
        for k, v in changes.items():
            setattr(building, k, v)
        masks = [seg.masks[f.view_id] for f in seg.frames]
        frame = building.source_frame if building.source_frame is not None else best_frame_for_floors(masks)
        building = recompute(building, masks[frame], set(changes), masks)
        # Offline the corrected parameters give a prompt that is not cached: keep the model's categories and
        # chosen works, recompute quantities and cost. With paid requests the model is asked again.
        layer = RecordedDecision(report.decision) if self.llm == "offline" else self.decision
        new = evaluate(seg, building=building, decision_layer=layer, price_source=self.prices)
        sources = dict(data["sources"], building="operator",
                       decision=(data["sources"].get("decision", "") if self.llm == "offline"
                                 else self._source(self.decision)) if new.decision else "")
        extra = {"video": data.get("video"), "seconds": data.get("seconds"),
                 "revision": data.get("revision", 1) + 1, "created_at": data.get("created_at")}
        return save_result(seg, new, result_dir, data["inputs"], sources, extra)


# ---------- saving and loading ----------

def _summary(report: Report) -> dict:
    from core.reference import CONDITION_NAMES_UA, DAMAGE_NAMES_UA, ESCALATION_UA
    from core.report_pdf import summary_ua
    d, k, b = report.decision, report.cost, report.building
    real = d is not None and not d.is_stub
    shown = real and d.escalation != "insufficient_data"
    return {
        "text_ua": summary_ua(report),
        "has_assessment": shown,                 # false: no category to show, the case needs an engineer or input
        "damage_category": d.damage_category if shown else None,
        "damage_name_ua": DAMAGE_NAMES_UA[d.damage_category] if shown else None,
        "condition_category": d.condition_category if shown else None,
        "condition_name_ua": CONDITION_NAMES_UA[d.condition_category] if shown else None,
        "confidence": d.confidence if real else None,
        "escalation": d.escalation if real else None,
        "escalation_ua": ESCALATION_UA[d.escalation] if real else None,
        "cost_low": round(k.low) if shown and k and k.total > 0 else None,
        "cost_high": round(k.high) if shown and k and k.total > 0 else None,
        "cost_total": round(k.total) if shown and k and k.total > 0 else None,
        "currency": k.currency if k else "UAH",
        "prices_as_of": k.as_of if k else None,
        "not_restorable": shown and d.damage_category == "III",   # true: no works and no cost, NOT_RESTORABLE_UA
        "floors": b.floors if b else None,
        "views_assessed": report.views_assessed,
        "errors": report.errors,
    }


def _report_dict(report: Report) -> dict:
    d = dataclasses.asdict(dataclasses.replace(report, masks={}, excluded={}))
    d.pop("masks")
    d.pop("excluded")
    return json.loads(json.dumps(d, default=list))       # sets become lists, int keys become strings


def save_result(seg, report: Report, out_dir: Path, inputs: list[dict], sources: dict, extra: dict) -> dict:
    from core.imageio import overlay
    from core.report_pdf import build_pdf

    out_dir.mkdir(parents=True, exist_ok=True)
    views_dir = out_dir / "views"
    shutil.rmtree(views_dir, ignore_errors=True)
    views_dir.mkdir()
    views = []
    for f in report.frames:
        i = f.view_id
        stem = f"view{i}"
        Image.fromarray(seg.images[i]).save(views_dir / f"{stem}.jpg", quality=92)
        Image.fromarray(seg.masks[i]).save(views_dir / f"{stem}_mask.png")
        other = seg.excluded.get(i)
        if other is not None:
            Image.fromarray((other * 255).astype(np.uint8)).save(views_dir / f"{stem}_other.png")
        Image.fromarray(overlay(seg.images[i], seg.masks[i], excluded=other)).save(
            views_dir / f"{stem}_overlay.jpg", quality=88)
        views.append({"view_id": i, "image": f"views/{stem}.jpg", "overlay": f"views/{stem}_overlay.jpg",
                      "mask": f"views/{stem}_mask.png",
                      "other_buildings": f"views/{stem}_other.png" if other is not None else None,
                      "worst": i in {report.ratios.worst_facade_view, report.ratios.worst_section_view}})
    (out_dir / "report.pdf").write_bytes(build_pdf(report, seg.images))
    now = datetime.now().isoformat(timespec="seconds")
    data = {
        "format_version": FORMAT_VERSION,
        "case_id": report.case_id,
        "mode": report.mode,
        "created_at": extra.get("created_at") or now,
        "updated_at": now,
        "revision": extra.get("revision", 1),
        "simulated": False,
        "sources": sources,
        "inputs": inputs,
        "seconds": extra.get("seconds"),
        "video": extra.get("video"),
        "summary": _summary(report),
        "views": views,
        "pdf": "report.pdf",
        "skipped_views": {str(k): v for k, v in report.skipped_frames.items()},
        "report": _report_dict(report),
    }
    (out_dir / "result.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _dc(cls, d):
    if d is None:
        return None
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def report_from_dict(r: dict) -> Report:
    b = r.get("building")
    if b is not None:
        b = dict(b, auto_detected=set(b.get("auto_detected") or []))
    d = r.get("decision")
    if d is not None:
        d = dict(d, works=[_dc(WorkItem, w) for w in d["works"]], facade=_dc(FacadeState, d.get("facade")))
    k = r.get("cost")
    if k is not None:
        k = dict(k, lines=[_dc(CostLine, x) for x in k["lines"]])
    return Report(
        case_id=r["case_id"], mode=r["mode"], views_assessed=r["views_assessed"],
        frames=[_dc(FrameMetrics, f) for f in r["frames"]], ratios=_dc(CombinedRatios, r["ratios"]),
        building=_dc(BuildingParams, b), areas=_dc(DamagedAreas, r.get("areas")), decision=_dc(Decision, d),
        cost=_dc(CostEstimate, k), skipped_frames={int(i): e for i, e in (r.get("skipped_frames") or {}).items()},
        errors=list(r.get("errors") or []))


def load_result(result_dir: Path):
    """(Segmentation, Report, result.json content) from a saved folder: enough to re-evaluate or rebuild the PDF."""
    from core.pipeline import Segmentation
    from core.types import Case, View

    result_dir = Path(result_dir)
    data = json.loads((result_dir / "result.json").read_text(encoding="utf-8"))
    report = report_from_dict(data["report"])
    seg = Segmentation(case=Case(report.case_id, report.mode, []), frames=report.frames,
                       skipped=report.skipped_frames)
    for v in data["views"]:
        i = v["view_id"]
        seg.case.views.append(View(i, result_dir / v["image"]))
        seg.images[i] = np.asarray(Image.open(result_dir / v["image"]).convert("RGB"))
        seg.masks[i] = np.asarray(Image.open(result_dir / v["mask"]), dtype=np.uint8)
        if v.get("other_buildings"):
            seg.excluded[i] = np.asarray(Image.open(result_dir / v["other_buildings"])) > 0
    report.masks, report.excluded = seg.masks, seg.excluded
    return seg, report, data


# ---------- choosing the engine ----------

_engine = None


def get_engine():
    """One engine per process. DAMAGE_ENGINE=simulator (with DAMAGE_PACK=<pack folder>) needs no weights,
    no key and no torch; anything else loads the real model."""
    global _engine
    if _engine is None:
        if os.environ.get("DAMAGE_ENGINE", "real") == "simulator":
            from core.simulator import SimulatedEngine
            _engine = SimulatedEngine()
        else:
            _engine = Engine()
    return _engine
