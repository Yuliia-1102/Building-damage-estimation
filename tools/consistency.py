"""Consistency check (task 9.4): did repeated runs give the same categories for every case?

    uv run python -m tools.consistency output/consistency.csv
"""
import argparse
import csv
from collections import defaultdict


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("results")
    args = p.parse_args()
    runs = defaultdict(list)
    for r in csv.DictReader(open(args.results, encoding="utf-8")):
        runs[r["case_id"]].append(r)
    unstable = 0
    for case, rows in runs.items():
        damage = [r["damage_category"] for r in rows]
        cond = [r["condition_category"] for r in rows]
        conf = [float(r["confidence"]) for r in rows if r["confidence"]]
        stable = len(set(damage)) == 1 and len(set(cond)) == 1
        unstable += not stable
        spread = f"{min(conf):.2f}-{max(conf):.2f}" if conf else "-"
        print(f"{'OK      ' if stable else 'UNSTABLE'} {case:24} damage {damage} condition {cond} confidence {spread}")
    n_runs = max(len(v) for v in runs.values())
    print(f"\n{len(runs) - unstable} of {len(runs)} cases gave the same categories in all {n_runs} runs")


if __name__ == "__main__":
    main()
