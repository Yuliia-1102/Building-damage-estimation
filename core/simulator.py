"""Simulated processing for building and testing the web system without the model weights or an API key.

Same calls as core.service.Engine: process(inputs, out_dir, case_id, progress) and reevaluate(dir, changes).
Answers come from a pack of recorded cases (tools/make_pack.py, docs/web_system.md):
  - the uploaded files are matched with the pack's input files by SHA-256: a match returns that case's
    recorded result; any other upload gets a recorded result picked by its hash (marked "matched": false);
  - processing takes DAMAGE_SIM_DELAY seconds ("3-8" by default, "0" in tests), with progress reports;
  - it fails when a file name contains "fail", or at random with DAMAGE_SIM_FAIL_RATE (0..1, default 0),
    so the failed status of the board can be tested;
  - a file name containing "lowconf" gives a result without an assessment (insufficient data, no category
    and no cost), the case the operator must send back for more photos.
Every result it writes has "simulated": true. Simulated results are not real assessments: the web system
must not count them in the statistics shown at the defence, or must mark them.
"""
import json
import logging
import os
import random
import shutil
import time
from pathlib import Path

from core import config
from core.service import (InputError, Progress, RecordedDecision, _delay, describe_inputs, input_mode,
                          load_result, save_result)

log = logging.getLogger(__name__)


class SimulatedFailure(RuntimeError):
    pass


def _no_assessment(data: dict) -> None:
    """What a result looks like when the model is not sure: no categories, no cost (core.service._summary)."""
    from core.reference import ESCALATION_UA
    s = data["summary"]
    s.update(has_assessment=False, damage_category=None, damage_name_ua=None, condition_category=None,
             condition_name_ua=None, cost_low=None, cost_high=None, cost_total=None, confidence=0.3,
             escalation="insufficient_data", escalation_ua=ESCALATION_UA["insufficient_data"], text_ua=None)
    if data["report"].get("decision"):
        data["report"]["decision"].update(confidence=0.3, escalation="insufficient_data")


class SimulatedEngine:
    name = "simulator"

    def __init__(self, pack: Path | None = None, delay: tuple[float, float] | None = None,
                 fail_rate: float | None = None):
        self.pack = Path(pack or os.environ.get("DAMAGE_PACK") or config.ROOT / "devpack")
        index = self.pack / "index.json"
        if not index.exists():
            raise FileNotFoundError(f"no pack at {self.pack}: unpack devpack.zip there or set DAMAGE_PACK")
        self.cases = json.loads(index.read_text(encoding="utf-8"))["cases"]
        self.delay = delay or _delay()
        self.fail_rate = float(os.environ.get("DAMAGE_SIM_FAIL_RATE", 0)) if fail_rate is None else fail_rate

    def _match(self, hashes: list[str]) -> tuple[dict, bool]:
        wanted = set(hashes)
        for c in self.cases:
            if {i["sha256"] for i in c["inputs"]} == wanted:
                return c, True
        pick = int(hashes[0][:8], 16) % len(self.cases)
        return self.cases[pick], False

    def _wait(self, progress: Progress, steps: list[tuple[float, str]]) -> None:
        total = random.uniform(*self.delay)
        for share, text in steps:
            progress(share, text)
            time.sleep(total / len(steps))

    def process(self, inputs: list[Path], out_dir: Path, case_id: str | None = None,
                progress: Progress | None = None) -> dict:
        inputs = [Path(p) for p in inputs]
        mode = input_mode(inputs)
        progress = progress or (lambda share, text: None)
        files = describe_inputs(inputs)
        case_id = case_id or inputs[0].stem + (f"+{len(inputs) - 1}" if len(inputs) > 1 else "")
        steps = [(0.05, "Симуляція: підготовка"), (0.4, "Симуляція: сегментація"),
                 (0.8, "Симуляція: категорії і вартість")]
        if any("fail" in p.stem.lower() for p in inputs) or random.random() < self.fail_rate:
            self._wait(progress, steps[:2])
            raise SimulatedFailure("simulated processing failure")
        self._wait(progress, steps)
        case, matched = self._match([f["sha256"] for f in files])
        out_dir = Path(out_dir)
        if out_dir.exists():
            shutil.rmtree(out_dir)
        shutil.copytree(self.pack / case["result"], out_dir)
        data = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
        data.update(case_id=case_id, inputs=files, simulated=True,
                    simulation={"from_pack_case": case["case_id"], "matched": matched,
                                "uploaded_mode": mode})
        data["report"]["case_id"] = case_id
        if any("lowconf" in p.stem.lower() for p in inputs):
            _no_assessment(data)
        (out_dir / "result.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        progress(1.0, "Готово (симуляція)")
        log.info("simulated %s from pack case %s (matched=%s)", case_id, case["case_id"], matched)
        return data

    def reevaluate(self, result_dir: Path, changes: dict) -> dict:
        """Same rules as the real engine; the decision is kept from the recording, quantities and cost change."""
        import copy

        from core.building import best_frame_for_floors
        from core.pipeline import evaluate
        from models.gemini_building import recompute
        from models.price_source import default_price_source

        result_dir = Path(result_dir)
        seg, report, data = load_result(result_dir)
        if report.building is None:
            raise InputError("the result has no building parameters to correct")
        allowed = {"floors", "floor_height_m", "width_m", "depth_m", "roof_type", "structure_type"}
        if set(changes) - allowed:
            raise InputError("cannot change: " + ", ".join(sorted(set(changes) - allowed)))
        building = copy.deepcopy(report.building)
        for k, v in changes.items():
            setattr(building, k, v)
        masks = [seg.masks[f.view_id] for f in seg.frames]
        frame = building.source_frame if building.source_frame is not None else best_frame_for_floors(masks)
        building = recompute(building, masks[frame], set(changes), masks)
        new = evaluate(seg, building=building, decision_layer=RecordedDecision(report.decision),
                       price_source=default_price_source())
        extra = {"video": data.get("video"), "seconds": data.get("seconds"),
                 "revision": data.get("revision", 1) + 1, "created_at": data.get("created_at")}
        out = save_result(seg, new, result_dir, data["inputs"], dict(data["sources"], building="operator"), extra)
        out.update(simulated=True, simulation=data.get("simulation"))
        (result_dir / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out
