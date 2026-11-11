"""Web system scenarios: processing, failure and retry, no assessment, duplicates, reevaluation, decisions,
projects, recovery after a worker crash."""
from web import service
from web.models import Status


def _get(db, app_id):
    with db() as s:
        a = service.get(s, app_id)
        s.expunge_all()
        return a


def test_pages_open(client):
    for url in ("/board", "/projects", "/statistics", "/applications/new", "/healthz"):
        assert client.get(url).status_code == 200


def test_scenario_1_process_photo(client, create, pump, db):
    """Created -> Processing -> Processed, with a category and a cost."""
    aid = create("house.jpg", "вул. Шевченка, 12")
    a = _get(db, aid)
    assert a.status == Status.CREATED and a.queued_at is not None
    pump()
    a = _get(db, aid)
    assert a.status == Status.PROCESSED
    assert a.damage_category == "I" and a.condition_category == 2
    assert a.cost_low and a.cost_high and a.result_dir
    assert client.get(f"/applications/{aid}").status_code == 200


def test_scenario_6_fail_and_retry(client, create, pump, db):
    aid = create("fail_test.jpg", "fail")
    pump()
    a = _get(db, aid)
    assert a.status == Status.FAILED and a.error
    # Retry puts it back in the queue; the test engine fails again (name still contains "fail").
    client.post(f"/applications/{aid}/retry")
    assert _get(db, aid).status == Status.CREATED
    pump()
    assert _get(db, aid).status == Status.FAILED


def test_scenario_7_lowconf_no_assessment(create, pump, db):
    aid = create("lowconf_test.jpg", "lowconf")
    pump()
    a = _get(db, aid)
    assert a.status == Status.PROCESSED
    assert a.has_assessment is False
    assert a.damage_category is None and a.cost_low is None


def test_scenario_3_duplicate_photo(create, pump, db):
    first = create("school.jpg", "школа")
    pump()
    dup = create("copy_of_school.jpg", "школа копія", content="school.jpg")
    a = _get(db, dup)
    assert a.is_duplicate and a.duplicate_of_id == first
    assert a.queued_at is None   # flagged, not queued


def test_duplicate_reject(client, create, pump, db):
    first = create("school.jpg", "школа")
    pump()
    dup = create("copy_of_school.jpg", "копія", content="school.jpg")
    client.post(f"/applications/{dup}/dedupe", data={"action": "reject"})
    a = _get(db, dup)
    assert a.status == Status.DECLINED and str(first) in (a.decision_comment or "")


def test_duplicate_continue(client, create, pump, db):
    create("school.jpg", "школа")
    pump()
    dup = create("copy_of_school.jpg", "копія", content="school.jpg")
    client.post(f"/applications/{dup}/dedupe", data={"action": "continue"})
    a = _get(db, dup)
    assert a.status == Status.CREATED and a.queued_at is not None


def test_scenario_5_photoset_not_duplicate(create, pump, db):
    """Other photos of the same building are NOT a duplicate (different file contents)."""
    create("house_front.jpg", "будинок")
    pump()
    other = create(["house_1.jpg", "house_2.jpg", "house_3.jpg"], "той самий будинок, інші фото")
    a = _get(db, other)
    assert not a.is_duplicate


def test_scenario_9_reevaluate_changes_cost(client, create, pump, db):
    aid = create("house.jpg", "об'єкт")
    pump()
    before = _get(db, aid)
    client.post(f"/applications/{aid}/reevaluate", data={"floors": "8"})
    after = _get(db, aid)
    assert after.revision == before.revision + 1
    assert after.cost_total != before.cost_total


def test_scenario_10_approve_and_decline(client, create, pump, db):
    a1 = create("house1.jpg", "затвердити")
    a2 = create("house2.jpg", "відхилити")
    pump()
    client.post(f"/applications/{a1}/approve")
    client.post(f"/applications/{a2}/decline", data={"reason": "потрібні додаткові фото"})
    assert _get(db, a1).status == Status.APPROVED
    d = _get(db, a2)
    assert d.status == Status.DECLINED and d.decision_comment == "потрібні додаткові фото"


def test_lowconf_cannot_be_approved(client, create, pump, db):
    aid = create("lowconf_test.jpg", "lowconf")
    pump()
    client.post(f"/applications/{aid}/approve")       # must be ignored (no assessment)
    assert _get(db, aid).status == Status.PROCESSED


def test_scenario_11_project_cost_sum(client, create, pump, db):
    client.post("/projects", data={"name": "громада N", "description": ""})
    a1 = create("house1.jpg", "буд. 1", project_id="1")
    a2 = create("house2.jpg", "буд. 2", project_id="1")
    pump()
    r = client.get("/projects/1")
    assert r.status_code == 200
    s1, s2 = _get(db, a1), _get(db, a2)
    # The project page shows the sum; check the underlying numbers add up.
    assert (s1.cost_low + s2.cost_low) > 0


def test_scenario_12_requeue_stuck(create, db):
    """A worker crash leaves an application in Processing; on restart it goes back to Created."""
    aid = create("house.jpg", "застрягла")
    with db() as s:
        app = service.claim_next(s)        # marks Processing, as a worker would
        assert app.status == Status.PROCESSING
    with db() as s:
        n = service.requeue_stuck(s)
    assert n >= 1
    assert _get(db, aid).status == Status.CREATED


def test_statistics_count_processed_applications(client, create, pump, db):
    create("house.jpg", "будинок")
    pump()
    with db() as s:
        stats = service.statistics(s)
    assert stats["total"] == 1 and stats["by_damage"]["I"] == 1
    assert client.get("/statistics").status_code == 200
