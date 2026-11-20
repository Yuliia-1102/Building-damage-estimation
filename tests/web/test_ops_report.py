"""The operations report reads the request lines the server writes and raises the alert on failures."""
from tools.ops_report import minutes, parse

LOG = """\
2026-11-20 10:00:01,100 INFO web.access request rid=a1 user=operator1 method=GET path=/board status=200 outcome=ok ms=80.0
2026-11-20 10:00:02,100 INFO web.access request rid=a2 user=operator2 method=POST path=/applications/1/approve status=403 outcome=rejected ms=12.0
2026-11-20 10:01:01,100 INFO web.access request rid=b1 user=operator1 method=GET path=/board status=500 outcome=fail ms=30.0
2026-11-20 10:01:02,100 INFO web.access request rid=b2 user=- method=GET path=/healthz status=503 outcome=fail ms=5.0
2026-11-20 10:01:03,100 INFO web.audit audit rid=b1 user=operator1 action=login object=user:1 result=ok
"""


def test_minutes_and_alert(tmp_path):
    log = tmp_path / "web.log"
    log.write_text(LOG, encoding="utf-8")
    rows = parse(log)
    assert len(rows) == 4                                    # audit lines are not requests
    m = minutes(rows)
    assert [(x["ok"], x["rejected"], x["fail"], x["alert"]) for x in m] == [(1, 1, 0, False), (0, 0, 2, True)]


def test_server_writes_request_lines(client, tmp_path):
    from web import config
    client.get("/board")
    rows = parse(config.LOGS_DIR / "web.log")
    assert any(r["path"] == "/board" and r["user"] == "operator1" and r["outcome"] == "ok" for r in rows)
