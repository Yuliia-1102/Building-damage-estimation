"""Operations report from the web log: successful and failed requests and their duration, per minute.

    python -m tools.ops_report                       # the whole <data>/logs/web.log
    python -m tools.ops_report --since "2026-11-20 10:00" --until "2026-11-20 11:00"

Alert rule (the threshold for the incident drill): a minute is marked ALERT when at least 3 requests ended
with a server error (5xx), or more than 20 % of its requests did, or /healthz answered 503.
Outcomes: ok (<400), rejected (4xx: validation, permission, conflict - the system worked), fail (5xx).
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LINE = re.compile(r"^(?P<ts>\S+ \S+?),\d+ \S+ web\.access request rid=(?P<rid>\S+) user=(?P<user>\S+) "
                  r"method=(?P<method>\S+) path=(?P<path>\S+) status=(?P<status>\d+) outcome=(?P<outcome>\S+) "
                  r"ms=(?P<ms>[\d.]+)")
ALERT_FAILS, ALERT_SHARE = 3, 0.20


def parse(path: Path, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line)
        if not m:
            continue
        r = m.groupdict()
        r["ts"] = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        if (since and r["ts"] < since) or (until and r["ts"] > until):
            continue
        r["status"], r["ms"] = int(r["status"]), float(r["ms"])
        rows.append(r)
    return rows


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]


def minutes(rows: list[dict]) -> list[dict]:
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[r["ts"].replace(second=0)].append(r)
    out = []
    for minute in sorted(buckets):
        b = buckets[minute]
        fails = sum(r["outcome"] == "fail" for r in b)
        health_down = any(r["path"] == "/healthz" and r["status"] == 503 for r in b)
        out.append({
            "minute": minute, "total": len(b), "ok": sum(r["outcome"] == "ok" for r in b),
            "rejected": sum(r["outcome"] == "rejected" for r in b), "fail": fails,
            "p95_ms": p95([r["ms"] for r in b]),
            "alert": fails >= ALERT_FAILS or (fails / len(b)) > ALERT_SHARE or health_down,
        })
    return out


def main() -> None:
    from web import config
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--log", type=Path, default=config.LOGS_DIR / "web.log")
    p.add_argument("--since")
    p.add_argument("--until")
    a = p.parse_args()
    fmt = "%Y-%m-%d %H:%M"
    rows = parse(a.log, datetime.strptime(a.since, fmt) if a.since else None,
                 datetime.strptime(a.until, fmt) if a.until else None)
    print(f"requests: {len(rows)}  ok: {sum(r['outcome'] == 'ok' for r in rows)}  "
          f"rejected: {sum(r['outcome'] == 'rejected' for r in rows)}  fail: {sum(r['outcome'] == 'fail' for r in rows)}  "
          f"p95: {p95([r['ms'] for r in rows]):.0f} ms")
    print(f"\n{'minute':16} {'total':>5} {'ok':>4} {'rej':>4} {'fail':>4} {'p95 ms':>7}")
    for m in minutes(rows):
        print(f"{m['minute']:%Y-%m-%d %H:%M} {m['total']:5} {m['ok']:4} {m['rejected']:4} {m['fail']:4} "
              f"{m['p95_ms']:7.0f}{'  ALERT' if m['alert'] else ''}")
    failed = [r for r in rows if r["outcome"] == "fail"]
    if failed:
        print("\nfailed requests (find the same rid in web.log and in the audit log):")
        for r in failed[-20:]:
            print(f"  {r['ts']} rid={r['rid']} user={r['user']} {r['method']} {r['path']} -> {r['status']}")


if __name__ == "__main__":
    main()
