"""Quality requirement QR-3 (performance): the board with 1 000 applications.

Condition: a temporary data folder with 1 000 processed applications, one signed-in operator, the server in the
same process (FastAPI TestClient), 10 warm-up requests, then 100 sequential GET /board.
Threshold: p95 <= 1 000 ms. The result is written to docs/v2/measurements/board_p95.json.

    uv run python -m tools.measure_board
"""
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ["DAMAGE_WEB_DATA"] = tempfile.mkdtemp(prefix="measure_")
os.environ.setdefault("DAMAGE_ENGINE", "simulator")

N_APPS, WARMUP, RUNS, THRESHOLD_MS = 1000, 10, 100, 1000


def main() -> None:
    from fastapi.testclient import TestClient

    from web.db import session_scope
    from web.models import Application, Status, User
    from web.server import app

    with session_scope() as s:
        owner = s.query(User).filter_by(username="operator1").one()
        start = datetime.now() - timedelta(days=30)
        statuses = [Status.PROCESSED, Status.APPROVED, Status.DECLINED, Status.FAILED]
        for i in range(N_APPS):
            s.add(Application(title=f"вул. Тестова, {i}", status=statuses[i % 4], owner_id=owner.id, mode="photo",
                              created_at=start + timedelta(minutes=i), has_assessment=True,
                              damage_category=["I", "II", "III"][i % 3], condition_category=1 + i % 4,
                              cost_low=100_000 + i, cost_high=150_000 + i, cost_total=125_000 + i))
    client = TestClient(app)
    client.post("/login", data={"username": "operator1", "password": os.environ.get("DAMAGE_DEMO_PASSWORD",
                                                                                     "demo2026")})
    for _ in range(WARMUP):
        assert client.get("/board").status_code == 200
    times = []
    for _ in range(RUNS):
        t = time.perf_counter()
        r = client.get("/board")
        times.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 200
    times.sort()
    p95 = times[int(round(0.95 * (len(times) - 1)))]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    result = {
        "requirement": "QR-3: board with 1000 applications, p95 of 100 sequential GET /board after 10 warm-up",
        "threshold_ms": THRESHOLD_MS, "p50_ms": round(statistics.median(times), 1), "p95_ms": round(p95, 1),
        "max_ms": round(times[-1], 1), "passed": p95 <= THRESHOLD_MS, "applications": N_APPS,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "commit": commit, "measured_at": datetime.now().isoformat(timespec="seconds"),
        "tool": "tools/measure_board.py (FastAPI TestClient, SQLite)",
    }
    out = Path(__file__).resolve().parents[1] / "docs" / "v2" / "measurements" / "board_p95.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
