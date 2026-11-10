"""Build the pack of recorded cases for the web system and its simulator (core/simulator.py).

    uv run python -m tools.make_pack                       # cached answers only, nothing is paid
    uv run python -m tools.make_pack --llm claude          # development answers through models/claude_bridge.py
    uv run python -m tools.make_pack --zip                 # also writes devpack.zip next to the repository

Every case of testset/cases.csv is processed with core.service.Engine (the same call the web worker makes)
and written to the pack:
  devpack/index.json              cases, their input files with SHA-256, expected categories, recorded summary
  devpack/inputs/<case_id>/       the files to upload in the web system
  devpack/inputs/_duplicates/     renamed copies of pack files: uploading one must raise a duplicate warning
  devpack/inputs/_special/        simulator scenarios by file name: fail_test (processing fails),
                                  lowconf_test (no assessment), new_building (a file the pack does not know)
  devpack/results/<case_id>/      the recorded result folder (docs/web_system.md, section 4)
  devpack/README.md               what is where, in short
"""
import argparse
import csv
import glob
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from core import config
from core.service import Engine, describe_inputs

log = logging.getLogger("make_pack")

README = """# Development pack: recorded cases

Built {built} by tools/make_pack.py, language model answers: {llm}.
How to use it: docs/web_system.md in the repository.

- `inputs/<case_id>/`: the files to upload, one folder = one application (a video, one photo or a photo set).
- `inputs/_duplicates/`: renamed copies of files above. Uploading one must give a duplicate warning.
- `inputs/_special/`: simulator scenarios by file name: `fail_test` fails, `lowconf_test` has no assessment,
  `new_building` is a file the pack does not know (a recorded result is returned, marked as not matched).
- `results/<case_id>/`: the recorded result for those inputs, format in docs/web_system.md, section 4.
- `index.json`: all cases with SHA-256 of their files and the recorded category and cost.

Development answers ("sources" in result.json says where each part came from) are not final results.
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cases", type=Path, default=config.ROOT / "testset" / "cases.csv")
    p.add_argument("--out", type=Path, default=config.ROOT / "devpack")
    p.add_argument("--llm", choices=["offline", "claude", "gemini"], default="offline",
                   help="offline: cached answers only (free); gemini: paid requests for answers not cached")
    p.add_argument("--only", nargs="*")
    p.add_argument("--zip", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    engine = Engine(llm=args.llm)
    out = args.out
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    index_path = out / "index.json"
    previous = {c["case_id"]: c for c in json.loads(index_path.read_text())["cases"]} if index_path.exists() else {}
    rows = list(csv.DictReader(open(args.cases, encoding="utf-8")))
    if args.only:
        rows = [r for r in rows if r["case_id"] in args.only]
    for row in rows:
        cid = row["case_id"]
        src = sorted(Path(x) for x in glob.glob(str(config.ROOT / row["input"])))
        if not src:
            log.error("%s: no input files %s", cid, row["input"])
            continue
        in_dir = out / "inputs" / cid
        in_dir.mkdir(exist_ok=True)
        files = []
        for s in src:
            dst = in_dir / s.name
            if not dst.exists():
                shutil.copy2(s, dst)
            files.append(dst)
        data = engine.process(files, out / "results" / cid, case_id=cid,
                              progress=lambda share, text: log.info("%s: %3.0f%% %s", cid, share * 100, text))
        s = data["summary"]
        previous[cid] = {
            "case_id": cid, "kind": row["kind"], "mode": data["mode"], "inputs": describe_inputs(files),
            "upload": f"inputs/{cid}/", "result": f"results/{cid}",
            "expected_damage": row["expected_damage"], "expected_condition": row["expected_condition"],
            "about": row["notes"].split(".")[0], "sources": data["sources"],
            "damage_category": s["damage_category"], "condition_category": s["condition_category"],
            "escalation": s["escalation"], "cost_low": s["cost_low"], "cost_high": s["cost_high"],
            "errors": s["errors"]}
        log.info("%s: %s / %s, %s-%s UAH, sources %s, errors %s", cid, s["damage_category"],
                 s["condition_category"], s["cost_low"], s["cost_high"], data["sources"], s["errors"])

    dup = out / "inputs" / "_duplicates"
    dup.mkdir(exist_ok=True)
    for cid, name in (("photo_single", "copy_of_photo_single.jpg"), ("download10", "copy_of_download10.mp4")):
        if cid in previous:
            src = out / "inputs" / cid / previous[cid]["inputs"][0]["name"]
            if src.exists() and not (dup / name).exists():
                shutil.copy2(src, dup / name)
    special = out / "inputs" / "_special"
    special.mkdir(exist_ok=True)
    src = out / "inputs" / "photo_burned" / "download13_2.png"
    if src.exists():
        from PIL import Image
        img = Image.open(src).convert("RGB")
        for name, q in (("fail_test.jpg", 90), ("lowconf_test.jpg", 85), ("new_building.jpg", 80)):
            if not (special / name).exists():
                img.save(special / name, quality=q)      # new bytes: not a duplicate of the pack files
    cases = [previous[r["case_id"]] for r in csv.DictReader(open(args.cases, encoding="utf-8"))
             if r["case_id"] in previous]
    index_path.write_text(json.dumps({"built": datetime.now().isoformat(timespec="seconds"), "llm": args.llm,
                                      "cases": cases}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "README.md").write_text(README.format(built=datetime.now().date(), llm=args.llm), encoding="utf-8")
    if args.zip:
        archive = shutil.make_archive(str(config.ROOT.parent / "devpack"), "zip", out.parent, out.name)
        print(f"zip: {archive}")
    print(f"pack: {out} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
