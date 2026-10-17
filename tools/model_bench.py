"""Compare Gemini models on the same requests and record real token usage (model choice, stage 2).

    uv run python -m tools.model_bench --models gemini-3.5-flash-lite gemini-3.1-flash-lite --out output/bench.json

For every test case the building request (one photo + prompt) and the decision request (text only) are
built exactly as the pipeline builds them. The answers of the building model (gemini-3.8-flash) are taken from the cache
(no request is sent for it); the other models are asked the same thing, and their usage metadata
(input, output, thinking tokens) and latency are recorded. The decision prompt always uses the configured
model's building answer, so the decision models are compared on identical input.
"""
import argparse
import csv
import json
import logging
import time
from pathlib import Path

from core import cache, config, geometry, metrics
from core.cache import CachedSegmenter
from core.pipeline import segment_case
from models import gemini_building as gb
from models import gemini_decision as gd
from models.gemini_client import GeminiJSON, make_client
from tools.run_testset import build_case

log = logging.getLogger("bench")


class Recorder(GeminiJSON):
    """GeminiJSON that keeps the usage metadata of every request it sends."""
    usage: list = []

    def _request(self, contents, schema, system):
        from google.genai import types
        t = time.time()
        r = self.client.models.generate_content(
            model=self.model, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                               response_schema=schema, temperature=0.0,
                                               seed=config.get("decision", "seed")))
        u = r.usage_metadata
        self.usage.append({"model": self.model, "schema": schema.__name__, "seconds": round(time.time() - t, 1),
                           "input": u.prompt_token_count, "output": u.candidates_token_count or 0,
                           "thinking": u.thoughts_token_count or 0})
        return r.text


class NoClient:
    class models:
        @staticmethod
        def generate_content(**_):
            raise RuntimeError("not cached")


def cached(model, contents, schema, system, ns, key_parts):
    try:
        return GeminiJSON(client=NoClient(), model=model, retries=0).ask(contents, schema, system, ns, key_parts)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--cases", type=Path, default=Path("testset/cases.csv"))
    p.add_argument("--out", type=Path, default=Path("output/bench.json"))
    p.add_argument("--only", nargs="*")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    from google.genai import types
    from models.dino_embedder import DinoEmbedder
    from models.dinov2_unet import DinoV2Segmenter

    base = config.get("decision", "building_model")   # reference answers come from the cache
    client = make_client()
    segmenter = CachedSegmenter(DinoV2Segmenter(), config.path("weights").stem)
    emb = []
    root = args.cases.resolve().parent.parent
    rows = [r for r in csv.DictReader(open(args.cases, encoding="utf-8")) if not args.only or r["case_id"] in args.only]
    results = []
    for row in rows:
        seg = segment_case(build_case(row, root, lambda: emb[0] if emb else (emb.append(DinoEmbedder()) or emb[0])),
                           segmenter)
        ids = [f.view_id for f in seg.frames]
        masks = [seg.masks[i] for i in ids]
        i = gb.geom.best_frame_for_floors(masks)
        data = gb._jpeg(seg.images[ids[i]])
        b_contents = [types.Part.from_bytes(data=data, mime_type="image/jpeg"), gb.PROMPT]
        b_key = [gb.PROMPT, cache.text_key(data.hex())]
        base_b = cached(base, b_contents, gb.BuildingResponse, gb.SYSTEM_INSTRUCTION, "building", b_key)
        entry = {"case_id": row["case_id"], "expected": [row["expected_damage"], row["expected_condition"]],
                 "building": {}, "decision": {}}
        if base_b is None:
            log.warning("%s: no cached %s building answer, skipped", row["case_id"], base)
            continue
        entry["building"][base] = base_b.model_dump()
        ratios = metrics.combine(seg.frames)
        params = gb.params_from_answer(base_b, masks[i])
        areas = geometry.damaged_areas(ratios, params) if params.width_m and params.height_m else None
        prompt = gd.build_prompt(ratios, areas, params)
        d_args = ([prompt], gd.DecisionResponse, gd.SYSTEM_INSTRUCTION, "decisions", [prompt])
        base_d = cached(base, *d_args)
        if base_d is not None:
            entry["decision"][base] = base_d.model_dump()
        for m in args.models:
            llm = Recorder(client=client, model=m, retries=1, use_cache=True)
            for kind, call in (("building", (b_contents, gb.BuildingResponse, gb.SYSTEM_INSTRUCTION, "building", b_key)),
                               ("decision", d_args)):
                n = len(Recorder.usage)
                try:
                    entry[kind][m] = llm.ask(*call).model_dump()
                except Exception as e:
                    entry[kind][m] = {"error": str(e)[:200]}
                entry[kind][m]["usage"] = Recorder.usage[n:]
        results.append(entry)
        args.out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
        log.info("%s done", row["case_id"])
    print(f"results: {args.out}")


if __name__ == "__main__":
    main()
